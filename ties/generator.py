import os
import json
import copy
import shutil
import subprocess
import math
from collections import OrderedDict
from pathlib import Path
import warnings

import MDAnalysis as mda
import numpy as np

from ties.topology_superimposer import get_atoms_bonds_from_mol2, \
    superimpose_topologies, element_from_type, get_atoms_bonds_from_ac


def prepare_inputs(morph,
                   dir_prefix,
                   protein=None,
                   namd_script_loc=None,
                   submit_script=None,
                   scripts_loc=None,
                   tleap_in=None,
                   protein_ff=None,
                   ligand_ff=None,
                   net_charge=None,
                   ambertools_script_dir=None,
                   ambertools_tleap=None,
                   namd_prod=None,
                   hybrid_topology=False,
                   vmd_vis_script=None,
                   md_engine=False,
                   lambda_rep_dir_tree=False):

    cwd = dir_prefix / f'{morph.internal_name}'
    if not cwd.is_dir():
        cwd.mkdir(parents=True, exist_ok=True)

    # copy the protein complex .pdb
    if protein is not None:
        shutil.copy(protein, cwd / 'protein.pdb')

    # copy the hybrid ligand (topology and .frcmod)
    shutil.copy(morph.mol2, cwd / 'morph.mol2')
    shutil.copy(morph.frcmod, cwd / 'morph.frcmod')

    # determine the number of ions to neutralise the ligand charge
    if net_charge < 0:
        Na_num = math.fabs(net_charge)
        Cl_num = 0
    elif net_charge > 0:
        Cl_num = net_charge
        Na_num = 0
    else:
        Cl_num = Na_num = 0

    # copy the protein tleap input file (ambertools)
    # set the number of ions manually
    assert Na_num == 0 or Cl_num == 0, 'At this point the number of ions should have be resolved'
    leap_in_conf = open(ambertools_script_dir / tleap_in).read()
    if Na_num == 0:
        tleap_Na_ions = ''
    elif Na_num > 0:
        tleap_Na_ions = 'addIons sys Na+ %d' % Na_num
    if Cl_num == 0:
        tleap_Cl_ions = ''
    elif Cl_num > 0:
        tleap_Cl_ions = 'addIons sys Cl- %d' % Cl_num

    open(cwd / 'leap.in', 'w').write(leap_in_conf.format(protein_ff=protein_ff,
                                                              ligand_ff=ligand_ff,
                                                              NaIons=tleap_Na_ions,
                                                              ClIons=tleap_Cl_ions))

    # ambertools tleap: combine ligand+complex, solvate, generate amberparm
    log_filename = cwd / 'generate_sys_top.log'
    with open(log_filename, 'w') as LOG:
        try:
            subprocess.run([ambertools_tleap, '-s', '-f', 'leap.in'],
                           stdout=LOG, stderr=LOG,
                           cwd = cwd,
                           check=True, text=True, timeout=30)
            hybrid_solv = cwd / 'sys_solv.pdb' # generated
            # check if the solvation is correct
        except subprocess.CalledProcessError as E:
            print('ERROR: occurred when trying to parse the protein.pdb with tleap. ')
            print(f'ERROR: The output was saved in the directory: {cwd}')
            print(f'ERROR: can be found in the file: {log_filename}')
            raise E

    # for hybrid single-dual topology approach, we have to use a different approach

    # generate the merged .fep file
    complex_solvated_fep = cwd / 'sys_solv_fep.pdb'
    correct_fep_tempfactor(morph.summary, hybrid_solv, complex_solvated_fep,
                           hybrid_topology)

    # fixme - check that the protein does not have the same resname?

    # calculate PBC for an octahedron
    solv_oct_boc = extract_PBC_oct_from_tleap_log(cwd / "leap.log")

    # prepare NAMD input files for min+eq+prod
    if md_engine in ('NAMD', 'namd'):
        init_namd_file_min(namd_script_loc, cwd, "min.namd",
                           structure_name='sys_solv', pbc_box=solv_oct_boc)
        eq_namd_filenames = generate_namd_eq(namd_script_loc / "eq.namd", cwd)
        shutil.copy(namd_script_loc / namd_prod, cwd / 'prod.namd')

    # generate 4 different constraint .pdb files (it uses B column)
    constraint_files = create_4_constraint_files(hybrid_solv, cwd)

    # Generate the directory structure for all the lambdas, and copy the files
    if lambda_rep_dir_tree:
        for lambda_step in [0, 0.05] + list(np.linspace(0.1, 0.9, 9)) + [0.95, 1]:
            lambda_path = cwd / f'lambda_{lambda_step:.2f}'
            if not os.path.exists(lambda_path):
                os.makedirs(lambda_path)

            # for each lambda create 5 replicas
            for replica_no in range(1, 5 + 1):
                replica_dir = lambda_path / f'rep{replica_no}'
                if not os.path.exists(replica_dir):
                    os.makedirs(replica_dir)

                # set the lambda value for the directory,
                # this file is used by NAMD tcl scripts
                open(replica_dir / 'lambda', 'w').write(f'{lambda_step:.2f}')

                # copy the necessary files
                prepareFile(os.path.relpath(hybrid_solv, replica_dir), replica_dir / 'sys_solv.pdb')
                prepareFile(os.path.relpath(complex_solvated_fep, replica_dir), replica_dir / 'sys_solv_fep.pdb')
                # copy ambertools-generated topology
                prepareFile(os.path.relpath(cwd / "sys_solv.top", replica_dir), replica_dir / "sys_solv.top")
                # copy the .pdb files with constraints in the B column
                for constraint_file in constraint_files:
                    prepareFile(os.path.relpath(constraint_file, replica_dir),
                                replica_dir / os.path.basename(constraint_file))

                # copy the NAMD protocol files
                if md_engine in ('NAMD', 'namd'):
                    prepareFile(os.path.relpath(cwd / 'min.namd', replica_dir), replica_dir / 'min.namd')
                    [prepareFile(os.path.relpath(eq, replica_dir), replica_dir / os.path.basename(eq))
                                for eq in eq_namd_filenames]
                    prepareFile(os.path.relpath(cwd / 'prod.namd', replica_dir), replica_dir / 'prod.namd')

                # copy a submit script
                if submit_script is not None:
                    shutil.copy(namd_script_loc / submit_script, replica_dir / 'submit.sh')

    # copy the visualisation script as hidden
    shutil.copy(vmd_vis_script, cwd / 'vis.vmd')
    # simplify the vis.vmd use
    vis_sh = Path(cwd / 'vis.sh')
    vis_sh.write_text('#!/bin/sh \nvmd -e vis.vmd')
    vis_sh.chmod(0o755)


def _merge_frcmod_section(ref_lines, other_lines):
    """
    A helper function for merging lines in .frcmod files.
    Note that the order has to be kept. This is because some lines need to follow other lines.
    In this case, we exclude lines that are present in ref_lines.
    fixme - since there are duplicate lines, we need to check the duplicates and their presence,
    """
    merged_section = copy.copy(ref_lines)
    for line in other_lines:
        if line not in ref_lines:
            merged_section.append(line)

    return merged_section


def join_frcmod_files(f1, f2, output_filepath):
    """
    This implementation should be used. Switch to join_frcmod_files2.
    This version might be removed if the simple approach is fine.
    """
    # fixme - load f1 and f2

    def get_section(name, rlines):
        """
        Chips away from the lines until the section is ready

        fixme is there a .frcmod reader in ambertools?
        http://ambermd.org/FileFormats.php#frcmod
        """
        section_names = ['MASS', 'BOND', 'ANGLE', 'DIHE', 'IMPROPER', 'NONBON']
        assert name in rlines.pop().strip()

        section = []
        while not (len(rlines) == 0 or any(rlines[-1].startswith(sname) for sname in section_names)):
            nextl = rlines.pop().strip()
            if nextl == '':
                continue
            # depending on the column name, parse differently
            if name == 'ANGLE':
                # e.g.
                # c -cc-na   86.700     123.270   same as c2-cc-na, penalty score=  2.6
                atom_types = nextl[:8]
                other = nextl[9:].split()[::-1]
                # The harmonic force constants for the angle "ITT"-"JTT"-
                #                     "KTT" in units of kcal/mol/(rad**2) (radians are the
                #                     traditional unit for angle parameters in force fields).
                harmonicForceConstant = float(other.pop())
                # TEQ        The equilibrium bond angle for the above angle in degrees.
                eq_bond_angle = float(other.pop())
                # the overall angle
                section.append([atom_types, harmonicForceConstant, eq_bond_angle])
            elif name == 'DIHE':
                # e.g.
                # ca-ca-cd-cc   1    0.505       180.000           2.000      same as c2-ce-ca-ca, penalty score=229.0
                atom_types = nextl[:11]
                other = nextl[11:].split()[::-1]
                """
                IDIVF      The factor by which the torsional barrier is divided.
                    Consult Weiner, et al., JACS 106:765 (1984) p. 769 for
                    details. Basically, the actual torsional potential is

                           (PK/IDIVF) * (1 + cos(PN*phi - PHASE))

                 PK         The barrier height divided by a factor of 2.

                 PHASE      The phase shift angle in the torsional function.

                            The unit is degrees.

                 PN         The periodicity of the torsional barrier.
                            NOTE: If PN .lt. 0.0 then the torsional potential
                                  is assumed to have more than one term, and the
                                  values of the rest of the terms are read from the
                                  next cards until a positive PN is encountered.  The
                                  negative value of pn is used only for identifying
                                  the existence of the next term and only the
                                  absolute value of PN is kept.
                """
                IDIVF = float(other.pop())
                PK = float(other.pop())
                PHASE = float(other.pop())
                PN = float(other.pop())
                section.append([atom_types, IDIVF, PK, PHASE, PN])
            elif name == 'IMPROPER':
                # e.g.
                # cc-o -c -o          1.1          180.0         2.0          Using general improper torsional angle  X- o- c- o, penalty score=  3.0)
                # ...  IDIVF , PK , PHASE , PN
                atom_types = nextl[:11]
                other = nextl[11:].split()[::-1]
                # fixme - what is going on here? why is not generated this number?
                # IDIVF = float(other.pop())
                PK = float(other.pop())
                PHASE = float(other.pop())
                PN = float(other.pop())
                if PN < 0:
                    raise Exception('Unimplemented - ordering using with negative 0')
                section.append([atom_types, PK, PHASE, PN])
            else:
                section.append(nextl.split())
        return {name: section}

    def load_frcmod(filepath):
        # remark line
        rlines = open(filepath).readlines()[::-1]
        assert 'Remark' in rlines.pop()

        parsed = OrderedDict()
        for section_name in ['MASS', 'BOND', 'ANGLE', 'DIHE', 'IMPROPER', 'NONBON']:
            parsed.update(get_section(section_name, rlines))

        return parsed

    def join_frcmod(left_frc, right_frc):
        joined = OrderedDict()
        for left, right in zip(left_frc.items(), right_frc.items()):
            lname, litems = left
            rname, ritems = right
            assert lname == rname

            joined[lname] = copy.copy(litems)

            if lname == 'MASS':
                if len(litems) > 0 or len(ritems) > 0:
                    raise Exception('Unimplemented')
            elif lname == 'BOND':
                for ritem in ritems:
                    if len(litems) > 0 or len(ritems) > 0:
                        if ritem not in joined[lname]:
                            raise Exception('Unimplemented')
            # ANGLE, e.g.
            # c -cc-na   86.700     123.270   same as c2-cc-na, penalty score=  2.6
            elif lname == 'ANGLE':
                for ritem in ritems:
                    # if the item is not in the litems, add it there
                    # extra the first three terms to determine if it is present
                    # fixme - note we are ignoring the "same as" note
                    if ritem not in joined[lname]:
                        joined[lname].append(ritem)
            elif lname == 'DIHE':
                for ritem in ritems:
                    if ritem not in joined[lname]:
                        joined[lname].append(ritem)
            elif lname == 'IMPROPER':
                for ritem in ritems:
                    if ritem not in joined[lname]:
                        joined[lname].append(ritem)
            elif lname == 'NONBON':
                # if they're empty
                if not litems and not ritems:
                    continue

                raise Exception('Unimplemented')
            else:
                raise Exception('Unimplemented')
        return joined

    def write_frcmod(frcmod, filename):
        with open(filename, 'w') as FOUT:
            FOUT.write('GENERATED .frcmod by joining two .frcmod files' + os.linesep)
            for sname, items in frcmod.items():
                FOUT.write(f'{sname}' + os.linesep)
                for item in items:
                    atom_types = item[0]
                    FOUT.write(atom_types)
                    numbers = ' \t'.join([str(n) for n in item[1:]])
                    FOUT.write(' \t' + numbers)
                    FOUT.write(os.linesep)
                # the ending line
                FOUT.write(os.linesep)

    left_frc = load_frcmod(f1)
    right_frc = load_frcmod(f2)
    joined_frc = join_frcmod(left_frc, right_frc)
    write_frcmod(joined_frc, output_filepath)


def _correct_fep_tempfactor_single_top(fep_summary, source_pdb_filename, new_pdb_filename):
    """
    Single topology version of function correct_fep_tempfactor.

    The left ligand has to be called INI
    And right FIN
    """
    u = mda.Universe(source_pdb_filename)
    if 'INI' not in u.atoms.resnames or 'FIN' not in u.atoms.resnames:
        raise Exception('Missing the resname "mer" in the pdb file prepared for fep')

    # dual-topology info
    # matched atoms are denoted -2 and 2 (morphing into each other)
    matched_disappearing = list(fep_summary['single_top_matched'].keys())
    matched_appearing = list( fep_summary['single_top_matched'].values())
    # disappearing is denoted by -1
    disappearing_atoms = fep_summary['single_top_disappearing']
    # appearing is denoted by 1
    appearing_atoms = fep_summary['single_top_appearing']

    # update the Temp column
    for atom in u.atoms:
        # ignore water and ions and non-ligand resname
        # we only modify the protein, so ignore the ligand resnames
        # fixme .. why is it called mer, is it tleap?
        if atom.resname != 'INI' and atom.resname != 'FIN':
            continue

        # if the atom was "matched", meaning present in both ligands (left and right)
        # then ignore
        # note: we only use the left ligand
        if atom.name.upper() in matched_disappearing:
            atom.tempfactor = -2
        elif atom.name.upper() in matched_appearing:
            atom.tempfactor = 2
        elif atom.name.upper() in disappearing_atoms:
            atom.tempfactor = -1
        elif atom.name.upper() in appearing_atoms:
            # appearing atoms should
            atom.tempfactor = 1
        else:
            raise Exception('This should never happen. It has to be one of the cases')

    u.atoms.write(new_pdb_filename)  # , file_format='PDB') - fixme?


def load_mda_u(filename):
    # Load a MDAnalysis file, but turn off warnings about the dual topology setting
    # fixme - fuse with the .pdb loading, no distinction needed
    warnings.filterwarnings(action='ignore', category=UserWarning,
                            message='Element information is absent or missing for a few atoms. '
                                    'Elements attributes will not be populated.'    # warning to ignore
                            )
    return mda.Universe(filename)


def correct_fep_tempfactor(fep_summary, source_pdb_filename, new_pdb_filename, hybrid_topology=False):
    """
    fixme - this function does not need to use the file?
    we have the json information available here.

    Sets the temperature column in the PDB file
    So that the number reflects the alchemical information
    Requires by NAMD in order to know which atoms
    appear (1) and which disappear (-1).
    """
    if hybrid_topology:
        # delegate correcting fep column in the pdb file
        return _correct_fep_tempfactor_single_top(fep_summary, source_pdb_filename, new_pdb_filename)

    u = load_mda_u(source_pdb_filename)
    if 'mer' not in u.atoms.resnames:
        raise Exception('Missing the resname "mer" in the pdb file prepared for fep')

    # dual-topology info
    matched = list(fep_summary['matched'].keys())
    appearing_atoms = fep_summary['appearing']
    disappearing_atoms = fep_summary['disappearing']

    # update the Temp column
    for atom in u.atoms:
        # ignore water and ions and non-ligand resname
        # we only modify the protein, so ignore the ligand resnames
        # fixme .. why is it called mer, is it tleap?
        if atom.resname != 'mer':
            continue

        # if the atom was "matched", meaning present in both ligands (left and right)
        # then ignore
        # note: we only use the left ligand
        if atom.name in matched:
            continue
        elif atom.name in appearing_atoms:
            # appearing atoms should
            atom.tempfactor = 1
        elif atom.name in disappearing_atoms:
            atom.tempfactor = -1
        else:
            raise Exception('This should never happen. It has to be one of the cases')

    u.atoms.write(new_pdb_filename)  # , file_format='PDB') - fixme?


def get_ligand_resname(filename):
    lig_resnames = mda.Universe(filename).residues.resnames
    assert len(lig_resnames) == 1
    return lig_resnames


def get_morphed_ligand_resnames(filename):
    lig_resnames = mda.Universe(filename).residues.resnames
    # assert len(lig_resnames) == 2
    return lig_resnames


def get_PBC_coords(pdb_file):
    """
    Return [x, y, z]
    """
    u = mda.Universe(pdb_file)
    x = np.abs(max(u.atoms.positions[:, 0]) - min(u.atoms.positions[:, 0]))
    y = np.abs(max(u.atoms.positions[:, 1]) - min(u.atoms.positions[:, 1]))
    z = np.abs(max(u.atoms.positions[:, 2]) - min(u.atoms.positions[:, 2]))
    return (x, y, z)


def extract_PBC_oct_from_tleap_log(leap_log):
    """
    http://ambermd.org/namd/namd_amber.html
    Return the 9 numbers for the truncated octahedron unit cell in namd
    cellBasisVector1  d         0.0            0.0
    cellBasisVector2  (-1/3)*d (2/3)sqrt(2)*d  0.0
    cellBasisVector3  (-1/3)*d (-1/3)sqrt(2)*d (-1/3)sqrt(6)*d
    """
    leapl_log_lines = open(leap_log).readlines()
    line_to_extract = "Total bounding box for atom centers:"
    line_of_interest = list(filter(lambda l: line_to_extract in l, leapl_log_lines))
    d1, d2, d3 = line_of_interest[-1].split(line_to_extract)[1].split()
    d1, d2, d3 = float(d1), float(d2), float(d3)
    assert d1 == d2 == d3
    # scale the d since after minimisation the system turns out to be much smaller
    d = d1 * 0.8
    return {
        'cbv1': d, 'cbv2': 0, 'cbv3': 0,
        'cbv4': (-1/3.0)*d, 'cbv5': (2/3.0)*np.sqrt(2)*d, 'cbv6': 0,
        'cbv7': (-1/3.0)*d, 'cbv8': (-1/3.0)*np.sqrt(2)*d, 'cbv9': (-1/3)*np.sqrt(6)*d,
    }


def prepare_antechamber_parmchk2(source_script, target_script, net_charge):
    """
    Prepare the ambertools scripts.
    Particularly, create the scritp so that it has the net charge
    # fixme - run antechamber directly with the right settings from here?
    # fixme - check if antechamber has a python interface?
    """
    net_charge_set = open(source_script).read().format(net_charge=net_charge)
    open(target_script, 'w').write(net_charge_set)


def set_charges_from_ac(mol2_filename, ac_ref_filename):
    # ! the mol file will be overwritten
    print('Overwriting the mol2 file with charges from the ac file')
    # load the charges from the .ac file
    ac_atoms, _ = get_atoms_bonds_from_ac(ac_ref_filename)
    # load the .mol2 files with MDAnalysis and correct the charges
    mol2 = load_mol2_wrapper(mol2_filename)

    for mol2_atom in mol2.atoms:
        found_match = False
        for ac_atom in ac_atoms:
            if mol2_atom.name.upper() == ac_atom.name.upper():
                found_match = True
                mol2_atom.charge = ac_atom.charge
                break
        assert found_match, "Could not find the following atom in the AC: " + mol2_atom.name

    # update the mol2 file
    mol2.atoms.write(mol2_filename)


def set_charges_from_mol2(mol2_filename, mol2_ref_filename, by_atom_name=False, by_index=False, by_general_atom_type=False):
    # mol2_filename will be overwritten!
    print(f'Overwriting {mol2_filename} mol2 file with charges from {mol2_ref_filename} file')
    # load the ref charges
    ref_mol2 = load_mol2_wrapper(mol2_ref_filename)
    # load the .mol2 files with MDAnalysis and correct the charges
    mol2 = load_mol2_wrapper(mol2_filename)

    if by_atom_name and by_index:
        raise ValueError('Cannot have both. They are exclusive')
    elif not by_atom_name and not by_index:
        raise ValueError('Either option has to be selected.')

    # save the sum of charges before
    ref_sum_q =  sum(a.charge for a in ref_mol2.atoms)

    if by_atom_name:
        for mol2_atom in mol2.atoms:
            if mol2_atom.type == 'DU':
                continue

            found_match = False
            for ref_atom in ref_mol2.atoms:
                if ref_atom.type == 'DU':
                    continue

                if mol2_atom.name.upper() == ref_atom.name.upper():
                    if found_match == True:
                        raise Exception('AtomNames are not unique or do not match')
                    found_match = True
                    mol2_atom.charge = ref_atom.charge
            assert found_match, "Could not find the following atom: " + mol2_atom.name
    elif by_general_atom_type:
        for mol2_atom in mol2.atoms:
            found_match = False
            for ref_atom in ref_mol2.atoms:
                if element_from_type[mol2_atom.type.upper()] == element_from_type[ref_atom.type.upper()]:
                    if found_match == True:
                        raise Exception('AtomNames are not unique or do not match')
                    found_match = True
                    mol2_atom.charge = ref_atom.charge
            assert found_match, "Could not find the following atom in the AC: " + mol2_atom.name
    elif by_index:
        for mol2_atom, ref_atom in zip(mol2.atoms, ref_mol2.atoms):
                atype = element_from_type[mol2_atom.type.upper()]
                reftype = element_from_type[ref_atom.type.upper()]
                if atype != reftype:
                    raise Exception(f"The found general type {atype} does not equal to the reference type {reftype} ")

                mol2_atom.charge = ref_atom.charge

    assert ref_sum_q == sum(a.charge for a in mol2.atoms)
    # update the mol2 file
    mol2.atoms.write(mol2_filename)


def get_protein_net_charge(working_dir, protein_file, ambertools_tleap, leap_input_file, prot_ff):
    """
    Use automatic ambertools solvation of a single component to determine what is the next charge of the system.
    This should be replaced with pka/propka or something akin.
    Note that this is unsuitable for the hybrid ligand: ambertools does not understand a hybrid ligand
    and might assign the wront net charge.
    """
    cwd = working_dir / 'prep' / 'prep_protein_to_find_net_charge'
    if not cwd.is_dir():
        cwd.mkdir()

    # copy the protein
    shutil.copy(working_dir / protein_file, cwd)

    # use ambertools to solvate the protein: set ion numbers to 0 so that they are determined automatically
    # fixme - consider moving out of the complex
    leap_in_conf = open(leap_input_file).read()
    ligand_ff = 'leaprc.gaff' # ignored but must be provided
    open(cwd / 'solv_prot.in', 'w').write(leap_in_conf.format(protein_ff=prot_ff, ligand_ff=ligand_ff,
                                                                          protein_file=protein_file))

    log_filename = cwd / "ties_tleap.log"
    with open(log_filename, 'w') as LOG:
        try:
            subprocess.run([ambertools_tleap, '-s', '-f', 'solv_prot.in'],
                           cwd = cwd,
                           stdout=LOG, stderr=LOG,
                           check=True, text=True,
                           timeout=60 * 2  # 2 minutes
                        )
        except subprocess.CalledProcessError as E:
            print('ERROR: tleap could generate a simple topology for the protein to check the number of ions. ')
            print(f'ERROR: The output was saved in the directory: {cwd}')
            print(f'ERROR: can be found in the file: {log_filename}')
            raise E


    # read the file to see how many ions were added
    u = mda.Universe(cwd / 'prot_solv.pdb')
    cl = len(u.select_atoms('name Cl-'))
    na = len(u.select_atoms('name Na+'))
    if cl > na:
        return cl-na
    elif cl < na:
        return -(na-cl)

    return 0


def prepareFile(src, dst, symbolic=True):
    """
    Either copies or sets up a relative link between the files.
    This allows for a quick switch in how the directory structure is organised.
    Using relative links means that the entire TIES ligand or TIES complex
    has to be moved together.
    However, one might want to be able to send a single replica anywhere and
    execute it independantly (suitable for BOINC).

    @type: 'sym' or 'copy'
    """
    if symbolic:
        # note that deleting all the files is intrusive, todo
        if os.path.isfile(dst):
            os.remove(dst)
        os.symlink(src, dst)
    else:
        if os.path.isfile(dst):
            os.remove(dst)
        shutil.copy(src, dst)



def set_coor_from_ref_by_named_pairs(mol2_filename, coor_ref_filename, output_filename, left_right_pairs_filename):
    """
    Set coordinates but use atom names provided by the user.

    Example of the left_right_pairs_filename content:
    # flip the first ring
    # move the first c and its h
    C32 C18
    H34 C19
    # second pair
    C33 C17
    # the actual matching pair
    C31 C16
    H28 H11
    # the second matching pair
    C30 C15
    H29 H12
    #
    C35 C14
    # flip the other ring with itself
    C39 C36
    C36 C39
    H33 H30
    H30 H33
    C37 C38
    C38 C37
    H31 H32
    H32 H31
    """
    # fixme - check if the names are unique

    # parse "left_right_pairs_filename
    # format per line: leftatom_name right_atom_name
    lines = open(left_right_pairs_filename).read().split(os.linesep)
    left_right_pairs = (l.split() for l in lines if not l.strip().startswith('#'))

    # load the ref coordinates
    ref_mol2 = load_mol2_wrapper(coor_ref_filename)
    # load the .mol2 files with MDAnalysis and correct the charges
    static_mol2 = load_mol2_wrapper(mol2_filename)
    # this is being modified
    mod_mol2 = load_mol2_wrapper(mol2_filename)


    for pair in left_right_pairs:
        print('find pair', pair)
        new_pos = False
        for mol2_atom in static_mol2.atoms:
            # check if we are assigning from another molecule
            for ref_atom in ref_mol2.atoms:
                if mol2_atom.name.upper() == pair[0] and ref_atom.name.upper() == pair[1]:
                    new_pos = ref_atom.position
            # check if we are trying to assing coords from the same molecule
            for another_atom in static_mol2.atoms:
                if mol2_atom.name.upper() == pair[0] and another_atom.name.upper() == pair[1]:
                    new_pos = another_atom.position

        if new_pos is False:
            raise Exception("Could not find this pair: " + str(pair))

        # assign the position to the right atom
        # find pair[0]
        found = False
        for atom in mod_mol2.atoms:
            if atom.name.upper() == pair[0]:
                atom.position = new_pos
                found = True
                break
        assert found


    # update the mol2 file
    mod_mol2.atoms.write(output_filename)


def rewrite_mol2_hybrid_top(file, single_top_atom_names):
    # in the  case of the hybrid single-dual topology in NAMD
    # the .mol2 files have to be rewritten so that
    # the atoms dual-topology atoms that appear/disappear
    # are placed at the beginning of the molecule
    # (single topology atoms have to be separted by
    # the same distance)
    shutil.copy(file, os.path.splitext(file)[0] + '_before_sdtop_reordering.mol2' )
    u = mda.Universe(file)
    # select the single top area, use their original order
    single_top_area = u.select_atoms('name ' +  ' '.join(single_top_atom_names))
    # all others are mutating
    dual_top_area = u.select_atoms('not name ' + ' '.join(single_top_atom_names))
    new_order_u = single_top_area + dual_top_area
    new_order_u.atoms.write(file)


def update_PBC_in_namd_input(namd_filename, new_pbc_box, structure_filename, constraint_lines=''):
    """
    fixme - rename this file since it generates the .eq files
    These are the lines we modify:
    cellBasisVector1	{cell_x}  0.000  0.000
    cellBasisVector2	 0.000  {cell_y}  0.000
    cellBasisVector3	 0.000  0.000 {cell_z}

    With x/y/z replacing the 3 values
    """
    assert len(new_pbc_box) == 3

    reformatted_namd_in = open(namd_filename).read().format(
        cell_x=new_pbc_box[0], cell_y=new_pbc_box[1], cell_z=new_pbc_box[2],
        constraints=constraint_lines, output='test_output', structure=structure_filename)

    # write to the file
    open(namd_filename, 'w').write(reformatted_namd_in)


def create_4_constraint_files(original_pdb, location):
    # Generate 4 constraint files and return the filenames
    """
coordinates  complex.pdb
constraints  on
consexp  2
consref  complex.pdb ;#need all positions
conskfile  constraint_f4.pdb
conskcol  B
    """

    def create_constraint(mda_universe, output, constraint):
        # for each atom, give the B column the right value
        for atom in mda_universe.atoms:
            # ignore water
            if atom.resname in ['WAT', 'Na+', 'TIP3W', 'TIP3']:
                continue

            # set each atom depending on whether it is a H or not
            if atom.name.upper().startswith('H'):
                atom.tempfactor = 0
            else:
                # restrain the heavy atom
                atom.tempfactor = constraint

        mda_universe.atoms.write(output)

    # create the 4 constraint files
    filenames = []
    u = mda.Universe(original_pdb)
    for i in range(1, 4 + 1):
        next_constraint_filename = location / f'constraint_f{i:d}.pdb'
        create_constraint(u, next_constraint_filename, i)
        filenames.append(next_constraint_filename)

    return filenames


def init_namd_file_min(from_dir, to_dir, filename, structure_name, pbc_box):
    min_namd_initialised = open(os.path.join(from_dir, filename)).read() \
        .format(structure_name=structure_name, **pbc_box)
    open(os.path.join(to_dir, filename), 'w').write(min_namd_initialised)


def generate_namd_eq(namd_eq, dst_dir, structure_name='sys_solv'):
    input_data = open(namd_eq).read()
    eq_namd_filenames = []
    for i in range(4):
        constraints = f"""
constraints  on
consexp  2
# use the same file for the position reference and the B column
consref  constraint_f{4 - i}.pdb ;#need all positions
conskfile  constraint_f{4 - i}.pdb
conskcol  B
        """
        if i == 0:
            prev_output = 'min_out'
        else:
            # take the output from the previous run
            prev_output = 'eq_out_%d' % i

        reformatted_namd_in = input_data.format(
            constraints=constraints, output='eq_out_%d' % (i + 1),
            prev_output=prev_output, structure_name=structure_name)
        # write to the file, start eq files count from 1
        next_eq_step_filename = dst_dir / ("eq_step%d.namd" % (i + 1))
        open(next_eq_step_filename, 'w').write(reformatted_namd_in)
        eq_namd_filenames.append(next_eq_step_filename)
    return eq_namd_filenames


def redistribute_charges(mda):
    """
    Calculate the original charges in the matched component.
    """


    return
