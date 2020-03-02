"""
Load two ligands, run the topology superimposer, and then
using the results, generate the NAMD input files.

todo - use ambertools python interface rather than ambertools directly,
       or find some other API bbblocks building blocks? or some other API,
       or create minimal your own
todo - adjust the input for surfsara for nwo
todo - estimate the size and legnth of the simulation, to adjust the number of cores/nodes
todo -

frcmod file format: `http://ambermd.org/FileFormats.php#frcmod`

Improvements Long Term:
 - adapt pathlib to work with the directories

"""
from topology_superimposer import get_atoms_bonds_from_mol2, superimpose_topologies, assign_coords_from_pdb
import os
import json
import numpy as np
import shutil
import sys
import subprocess
from collections import OrderedDict
import copy
import MDAnalysis as mda
from pathlib import Path, PurePosixPath, PosixPath


def getSuptop(mol1, mol2):
    # use mdanalysis to load the files
    leftlig_atoms, leftlig_bonds, rightlig_atoms, rightlig_bonds, mda_l1, mda_l2 = \
        get_atoms_bonds_from_mol2(mol1, mol2)

    # assign
    # fixme - Ideally I would reuse the mdanalysis data for this
    startLeft = None
    ligand1_nodes = {}
    for atomNode in leftlig_atoms:
        ligand1_nodes[atomNode.get_id()] = atomNode
        if atomNode.atomName == 'O3':
            startLeft = atomNode
    for nfrom, nto, btype in leftlig_bonds:
        ligand1_nodes[nfrom].bindTo(ligand1_nodes[nto], btype)

    startRight = None
    ligand2_nodes = {}
    for atomNode in rightlig_atoms:
        ligand2_nodes[atomNode.get_id()] = atomNode
        if atomNode.atomName == 'O7':
            startRight = atomNode
    for nfrom, nto, btype in rightlig_bonds:
        ligand2_nodes[nfrom].bindTo(ligand2_nodes[nto], btype)

    suptops = superimpose_topologies(ligand1_nodes.values(), ligand2_nodes.values(),
                                     starting_node_pairs=[(startLeft, startRight)])
    assert len(suptops) == 1
    return suptops[0], mda_l1, mda_l2


def save_superimposition_results(filepath):
    # fixme - check if the file exists
    with open(filepath, 'w') as FOUT:
        # use json format, only use atomNames
        data = {
                'matching': {str(n1): str(n2) for n1, n2 in suptop.matched_pairs},
                'appearing': list(map(str, suptop.get_appearing_atoms())),
                'disappearing': list(map(str, suptop.get_disappearing_atoms()))
                }
        FOUT.write(json.dumps(data, indent=4))


def write_dual_top_pdb(filepath):
    # fixme - find another library that can handle writing to a PDB file, mdanalysis?
    # save the ligand with all the appropriate atomic positions, write it using the pdb format
    # pdb file format: http://www.wwpdb.org/documentation/file-format-content/format33/sect9.html#ATOM
    # write a dual .pdb file
    with open(filepath, 'w') as FOUT:
        for atom in mda_l1.atoms:
            """
            There is only one forcefield which is shared across the two topologies. 
            Basically, we need to check whether the atom is in both topologies. 
            If that is the case, then the atom should have the same name, and therefore appear only once. 
            However, if there is a new atom, it should be specfically be outlined 
            that it is 1) new and 2) the right type
            """
            # write all the atoms if they are matched, that's the common part
            REMAINS = 0
            if suptop.contains_left_atomName(atom.name):
                line = f"ATOM  {atom.id:>5d} {atom.name:>4s} {atom.resname:>3s}  " \
                       f"{atom.resid:>4d}    " \
                       f"{atom.position[0]:>8.3f}{atom.position[1]:>8.3f}{atom.position[2]:>8.3f}" \
                       f"{1.0:>6.2f}{REMAINS:>6.2f}" + (' ' * 11) + \
                       '  ' + '  ' + '\n'
                FOUT.write(line)
            else:
                # this atom was not found, this means it disappears, so we should update the
                DISAPPEARING_ATOM = -1.0
                line = f"ATOM  {atom.id:>5d} {atom.name:>4s} {atom.resname:>3s}  " \
                       f"{atom.resid:>4d}    " \
                       f"{atom.position[0]:>8.3f}{atom.position[1]:>8.3f}{atom.position[2]:>8.3f}" \
                       f"{1.0:>6.2f}{DISAPPEARING_ATOM:>6.2f}" + \
                       (' ' * 11) + \
                       '  ' + '  ' + '\n'
                FOUT.write(line)
        # add atoms from the right topology,
        # which are going to be created
        for atom in mda_l2.atoms:
            if not suptop.contains_right_atomName(atom.name):
                APPEARING_ATOM = 1.0
                line = f"ATOM  {atom.id:>5d} {atom.name:>4s} {atom.resname:>3s}  " \
                       f"{atom.resid:>4d}    " \
                       f"{atom.position[0]:>8.3f}{atom.position[1]:>8.3f}{atom.position[2]:>8.3f}" \
                       f"{1.0:>6.2f}{APPEARING_ATOM:>6.2f}" + \
                       (' ' * 11) + \
                       '  ' + '  ' + '\n'
                FOUT.write(line)


def write_merged(suptop, merged_filename):
    # recreate the mol2 file that is merged and contains the correct atoms from both
    # mol2 format: http://chemyang.ccnu.edu.cn/ccb/server/AIMMS/mol2.pdf
    with open(merged_filename, 'w') as FOUT:
        bonds = suptop.getDualTopologyBonds()

        FOUT.write('@<TRIPOS>MOLECULE ' + os.linesep)
        # name of the molecule
        FOUT.write('merged ' + os.linesep)
        # num_atoms [num_bonds [num_subst [num_feat [num_sets]]]]
        # fixme this is tricky
        FOUT.write(f'{suptop.getUnqiueAtomCount():d} '
                   f'{len(bonds):d}' + os.linesep)
        # mole type
        FOUT.write('SMALL ' + os.linesep)
        # charge_type
        FOUT.write('NO_CHARGES ' + os.linesep)
        FOUT.write(os.linesep)

        # write the atoms
        FOUT.write('@<TRIPOS>ATOM ' + os.linesep)
        # atom_id atom_name x y z atom_type [subst_id [subst_name [charge [status_bit]]]]
        # e.g.
        #       1 O4           3.6010   -50.1310     7.2170 o          1 L39      -0.815300

        # so from the two topologies all the atoms are needed and they need to have a different atom_id
        # so we might need to name the atom_id for them, other details are however pretty much the same
        # the importance of atom_name is difficult to estimate

        # we are going to assign IDs in the superimposed topology in order to track which atoms have IDs
        # and which don't

        subst_id = 1    # resid basically
        # write all the atoms that were matched first with their IDs
        # prepare all the atoms, note that we use primarily the left ligand naming
        all_atoms = [left for left, right in suptop.matched_pairs] + suptop.get_unmatched_atoms()
        # reorder the list according to the ID
        all_atoms.sort(key=lambda atom: suptop.get_generated_atom_ID(atom))

        for atom in all_atoms:
            FOUT.write(f'{suptop.get_generated_atom_ID(atom)} {atom.atomName} '
                       f'{atom.position[0]:.4f} {atom.position[1]:.4f} {atom.position[2]:.4f} '
                       f'{atom.type.lower()} {subst_id} {atom.resname} {atom.charge:.6f} {os.linesep}')

        # for left_atom, _ in suptop.matched_pairs:
        #     # note that the atom id is the most important
        #     FOUT.write(f'{suptop.get_generated_atom_ID(left_atom)} {left_atom.atomName} '
        #                f'{left_atom.position[0]:.4f} {left_atom.position[1]:.4f} {left_atom.position[2]:.4f} '
        #                f'{left_atom.type} {subst_id} {left_atom.resname} {left_atom.charge} {os.linesep}')

        # write the IDs for the atoms which are appearing/disappearing
        # for unmatched in suptop.get_unmatched_atoms():
        #     FOUT.write(f'{suptop.get_generated_atom_ID(unmatched)} {unmatched.atomName} '
        #                f'{unmatched.position[0]:.4f} {unmatched.position[1]:.4f} {unmatched.position[2]:.4f} '
        #                f'{unmatched.type} {subst_id} {unmatched.resname} {unmatched.charge} {os.linesep}')

        FOUT.write(os.linesep)

        # write bonds
        FOUT.write('@<TRIPOS>BOND ' + os.linesep)

        # we have to list every bond:
        # 1) all the bonds between the paired atoms, so that part is easy
        # 2) bonds which link the disappearing atoms, and their connection to the paired atoms
        # 3) bonds which link the appearing atoms, and their connections to the paired atoms

        bond_counter = 1
        list(bonds)
        for bond_from_id, bond_to_id, bond_type in sorted(list(bonds), key=lambda b: b[:2]):
            # Bond Line Format:
            # bond_id origin_atom_id target_atom_id bond_type [status_bits]
            FOUT.write(f'{bond_counter} {bond_from_id} {bond_to_id} {bond_type}' + os.linesep)
            bond_counter += 1


def join_frcmod_files(f1, f2, output_filepath):
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
                if len(litems) > 0 or len(ritems) > 0:
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
        return joined

    def write_frcmod(frcmod, filename):
        with open(filename, 'w') as FOUT:
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
                print('hi')

    left_frc = load_frcmod(f1)
    right_frc = load_frcmod(f2)
    joined_frc = join_frcmod(left_frc, right_frc)
    write_frcmod(joined_frc, output_filepath)


def correct_fep_tempfactor(fep_json_filename, source_pdb_filename, new_pdb_filename):
    """
    fixme - this function does not need to use the file?
    we have the json information available here.
    """
    u = mda.Universe(source_pdb_filename)
    fep_meta_str = open(fep_json_filename).read()
    fep_meta = json.loads(fep_meta_str)

    left_matched = list(fep_meta['matching'].keys())
    appearing_atoms = fep_meta['appearing']
    disappearing_atoms = fep_meta['disappearing']

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
        if atom.name in left_matched:
            continue
        elif atom.name in appearing_atoms:
            # appearing atoms should
            atom.tempfactor = 1
        elif atom.name in disappearing_atoms:
            atom.tempfactor = -1

    u.atoms.write(new_pdb_filename ) # , file_format='PDB') - fixme?


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
            if atom.resname == 'WAT' or atom.resname == 'Na+':
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
    for i in range(1, 4+1):
        next_constraint_filename = location / f'constraint_f{i:d}.pdb'
        create_constraint(u, next_constraint_filename, i)
        filenames.append(next_constraint_filename)

    return filenames


def init_namd_file_min(from_dir, to_dir, filename, structure_name, pbc_box):
    min_namd_initialised = open(os.path.join(from_dir, filename)).read()\
        .format(structure_name=structure_name,
                cell_x=pbc_box[0], cell_y=pbc_box[1], cell_z=pbc_box[2])
    open(os.path.join(to_dir, filename), 'w').write(min_namd_initialised)


def init_namd_file_prod(from_dir, to_dir, filename, structure_name):
    min_namd_initialised = open(os.path.join(from_dir, filename)).read()\
        .format(structure_name=structure_name)
    open(os.path.join(to_dir, filename), 'w').write(min_namd_initialised)


def generate_namd_eq(namd_eq, dst_dir, structure_name):
    input_data = open(namd_eq).read()
    eq_namd_filenames = []
    for i in range(4):
        constraints = f"""
constraints  on
consexp  2
# use the same file for the position reference and the B column
consref  constraint_f{4 - i}.pdb ;#need all positions
conskfile  constraint_f{4- i}.pdb
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


workplace_root = Path('/home/dresio/code/BAC2020/namd_study/mcl_l8_l18')

# todo - check if there is left.pdb and right.pdb
if not (workplace_root / 'left.pdb').is_file():
    print('File left.pdb not found in', workplace_root)
    sys.exit(1)
elif not (workplace_root / 'left.pdb').is_file():
    print('File right.pdb not found in', workplace_root)
    sys.exit(1)
# copy the ambertools.sh for 1) creating .mol2 - antechamber, 2) optimising the structure with sqm
antechamber_sqm_script_name = 'assign_charge_parameters.sh'
script_dir = PurePosixPath('/home/dresio/code/BAC2020/scripts')
namd_script_dir = script_dir / 'namd'
ambertools_script_dir = script_dir / 'ambertools'
# fixme - what are the net charges?
shutil.copy(ambertools_script_dir / antechamber_sqm_script_name, workplace_root)
# execute the script (the script has to source amber.sh)
# do not do this if there is a .frcmod files
if not (workplace_root / 'left.frcmod').is_file():
    # fixme - add checks for other files
    output = subprocess.check_output(['sh', workplace_root / antechamber_sqm_script_name, 'left', 'right'])
    # todo - CHECK IF THE RESULTS ARE CORRECT

# load the files (.mol2) and superimpose the two topologies
# fixme - superimpose the molecules or stop relaying on RMSD info
# fixme - call any of the tools you have (antechamber, parmchk2)
suptop, mda_l1, mda_l2 = getSuptop(workplace_root / 'left.mol2',
                                   workplace_root / 'right.mol2')
# verify the suptop

# save the results of the topology superimposition as a json
top_sup_joint_meta = workplace_root / 'joint_meta_fep.json'
save_superimposition_results(top_sup_joint_meta)
write_dual_top_pdb(workplace_root / 'left_right.pdb')
# save the merged topologies as a .mol2 file
top_merged_filename = workplace_root / 'morph.mol2'
write_merged(suptop, top_merged_filename)

# check if the .frcmod were generated
left_frcmod = workplace_root / 'left.frcmod'
right_frcmod = workplace_root / 'right.frcmod'
if not left_frcmod.is_file():
    sys.exit(5)
elif not right_frcmod.is_file():
    sys.exit(5)

# generate the joint .frcmod file
merged_frc_filename = workplace_root / 'morph.frcmod'
join_frcmod_files(left_frcmod, right_frcmod, merged_frc_filename)

# copy the solvate script for tleap
shutil.copy(ambertools_script_dir / "run_tleap.sh", workplace_root)
shutil.copy(ambertools_script_dir / "leap.in", workplace_root)
# solvate using AmberTools, copy leap.in and use tleap
output = subprocess.check_output(['sh', workplace_root / "run_tleap.sh"])
# this generates the "merged_solvated.pdb" which does not have .fep information in the .pdb tempfactor columns
morph_solv = workplace_root / "morph_solv.pdb"
morph_solv_fep = workplace_root / "morph_solv_fep.pdb"
correct_fep_tempfactor(top_sup_joint_meta, morph_solv, morph_solv_fep)

# take care of the ligand-ligand without the protein
liglig_workplace = workplace_root / 'liglig'
if not liglig_workplace.is_dir():
    liglig_workplace.mkdir()

# generate the constraint files in liglig
constraint_files = create_4_constraint_files(morph_solv, liglig_workplace)
pbc_dimensions = get_PBC_coords(morph_solv)
init_namd_file_min(namd_script_dir, liglig_workplace, "min.namd",
                           structure_name='morph_solv', pbc_box=pbc_dimensions)
# prepare the namd eq
eq_namd_files = generate_namd_eq(namd_script_dir / "eq.namd", liglig_workplace, 'morph_solv')
# namd production protocol
init_namd_file_prod(namd_script_dir, liglig_workplace, "prod.namd", structure_name='morph_solv')

# Generate the directory structure for all the lambdas, and copy the files
for lambda_step in [0, 0.05] + list(np.linspace(0.1, 0.9, 9)) + [0.95, 1]:
    lambda_path = liglig_workplace / f'lambda_{lambda_step:.2f}'
    if not os.path.exists(lambda_path):
        os.makedirs(lambda_path)

    # for each lambda create 5 replicas
    for replica_no in range(1, 5 + 1):
        replica_dir = lambda_path / f'rep{replica_no}'
        if not os.path.exists(replica_dir):
            os.makedirs(replica_dir)
            # set the lambda value for the directory

        open(replica_dir / 'lambda', 'w').write(f'{lambda_step:.2f}')

        # copy the files for each simulation
        # "coordinates" with the fep metadata
        shutil.copy(morph_solv_fep, replica_dir)
        # copy the ambertools generated topology file
        shutil.copy(workplace_root / "morph_solv.top", replica_dir)
        # the normal coordinates
        shutil.copy(workplace_root / "morph_solv.pdb", replica_dir)

        # copy the restraint files, which use b column
        [shutil.copy(constraint_file, replica_dir) for constraint_file in constraint_files]

        # copy NAMD protocol
        shutil.copy(liglig_workplace / 'min.namd', replica_dir)
        [shutil.copy(eq, replica_dir) for eq in eq_namd_files]

        # todo - create/copy the 4 different EQ files
        # copy the surfsara submit script
        shutil.copy(script_dir / "surfsara.sh", replica_dir / 'submit.sh')

# copy the scheduler to the main directory
shutil.copy(script_dir / "schedule_separately.py", liglig_workplace)
shutil.copy(script_dir /"check_namd_outputs.py", liglig_workplace)

sys.exit(1)

##########################################################
# ------------------ complex-complex --------------
# fixme - use tleap to merge+solvate, decide on the charges?

complex_workplace = workplace_root / 'complexcomplex'
if not os.path.isdir(complex_workplace):
    os.makedirs(complex_workplace)

# prepare the simulation files
# copy the complex .pdb
shutil.copy(workplace_root / 'protein.pdb', complex_workplace)
# todo - ensure the protein protonation is correct
# todo - call antechamber?

# copy the ligand (the morphed ligand), and its .frcmod
shutil.copy(top_merged_filename, complex_workplace)
shutil.copy(workplace_root / merged_frc_filename, complex_workplace)

# todo - dock with the ligand to create a complex
# copy the protein tleap input file (ambertools)
shutil.copy(script_dir / 'leap_complex.in', complex_workplace)
shutil.copy(script_dir / 'run_tleap_complex.sh', complex_workplace)

# solvate the complex (tleap, ambertools)
#      rn tleap also combines complex+ligand, and generates amberparm
try:
    output = subprocess.check_output(['sh', complex_workplace / "run_tleap_complex.sh"],
                                 cwd=complex_workplace)
except Exception as ex:
    print(ex.output)
    raise ex
assert 'Errors = 0' in str(output)
# tleap generates these:
complex_solvated = complex_workplace / 'complex_solvated.pdb'

# update the complex to create complex.fep file
# generate the merged .fep file
complex_solvated_fep = workplace_root / 'complex_solvated_fep.pdb'
correct_fep_tempfactor(top_sup_joint_meta, complex_solvated, complex_solvated_fep)

# fixme - ensure that the _fep is only applied to the ligand, not the protein,
# fixme - check that the protein does not have the same resname

# get the PBC data from MDAnalysis
solv_box_complex_pbc = get_PBC_coords(complex_solvated)

# copy the NAMD input files to the main directory first
complex_eq_namd_filename = "complex_eq_template.namd"
shutil.copy(script_dir / complex_eq_namd_filename, complex_workplace)
complex_eq_namd = complex_workplace / complex_eq_namd_filename
complex_prod_namd_filename = "complex_prod.namd"
shutil.copy(script_dir / complex_prod_namd_filename, complex_workplace)
complex_prod_namd = complex_workplace / complex_prod_namd_filename
# modify the NAMD to reflect on the correct PBC boundaries
# update PBC in the .namd inputs
# update_PBC_in_namd_input(complex_eq_namd, solv_box_complex_pbc)

# copy the minmisation file
namd_input_min = script_dir / "min.namd"
shutil.copy(namd_input_min, complex_workplace)
update_PBC_in_namd_input(namd_input_min, solv_box_complex_pbc, 'complex_solvated')

# generate the 4 different constrain .pdb files files, which use b column
constraint_files = create_4_constraint_files(complex_solvated, complex_workplace)
# todo prepare four 4 eq input namd which have different constraints, this requires pbc info + constraint info
original_complex_eq_namd = script_dir / complex_eq_namd_filename
generate_namd_eq(original_complex_eq_namd, solv_box_complex_pbc, complex_workplace)


# Generate the directory structure for all the lambdas, and copy the files
for lambda_step in [0, 0.05] + list(np.linspace(0.1, 0.9, 9)) + [0.95, 1]:
    lambda_path = complex_workplace / f'lambda_{lambda_step:.2f}'
    if not os.path.exists(lambda_path):
        os.makedirs(lambda_path)

    # for each lambda create 5 replicas
    for replica_no in range(1, 5 + 1):
        replica_dir = lambda_path / f'rep{replica_no}'
        if not os.path.exists(replica_dir):
            os.makedirs(replica_dir)

        # set the lambda value for the directory
        with open(replica_dir / 'lambda', 'w') as FOUT:
            FOUT.write(f'{lambda_step:.2f}')

        # copy all the necessary files
        shutil.copy(complex_solvated_fep, replica_dir)
        shutil.copy(complex_solvated, replica_dir)

        # copy the ambertools generated topology
        shutil.copy(complex_workplace / "complex_solvated.top", replica_dir)

        # copy the NAMD protocol files
        shutil.copy(complex_workplace / "min.namd", replica_dir)
        shutil.copy(complex_workplace / "complex_eq_step1.namd", replica_dir)
        shutil.copy(complex_workplace / "complex_eq_step2.namd", replica_dir)
        shutil.copy(complex_workplace / "complex_eq_step3.namd", replica_dir)
        shutil.copy(complex_workplace / "complex_eq_step4.namd", replica_dir)
        shutil.copy(complex_workplace / "complex_prod.namd", replica_dir)

        # copy the .pdb files with constraints in the B column
        shutil.copy(complex_workplace / "constraint1_complex_solvated.pdb", replica_dir)
        shutil.copy(complex_workplace / "constraint2_complex_solvated.pdb", replica_dir)
        shutil.copy(complex_workplace / "constraint3_complex_solvated.pdb", replica_dir)
        shutil.copy(complex_workplace / "constraint4_complex_solvated.pdb", replica_dir)

        # copy the surfsara submit script - fixme - make this general
        shutil.copy(script_dir / "surfsara_complex.sh", replica_dir / 'submit.sh')

# copy the scheduler to the main directory
shutil.copy(script_dir / "schedule_separately.py", complex_workplace)
shutil.copy(script_dir / "check_namd_outputs.py", complex_workplace)


# todo

# set the lambda value for the directory
# with open(os.path.join(replica_dir, 'lambda'), 'w') as FOUT:
#     FOUT.write(f'{lambda_step:.2f}')

# copy the surfsara submit script - fixme - make this general
# shutil.copy(os.path.join(script_dir, "surfsara.sh"), os.path.join(replica_dir, 'submit.sh'))

# copy the scheduler to the main directory
# shutil.copy(os.path.join(script_dir, "schedule_separately.py"), liglig_workplace)
# shutil.copy(os.path.join(script_dir, "check_namd_outputs.py"), liglig_workplace)

# fixme States show the progress of the simulation.

# use the preprepared pdb complex with the ligand
# solvate the preprepared pdb complex with the ligand
# generate all the merged files 

"""
# todo - generate completely different directories with scripts with namd for each lambda
# todo - use sqlite to synchronise the execution and managing of all of the simulations? (ie one major script)
for example, imagine a script that says "do_ties" which knows that there is 13 x 5 different directories
which have to be run each, and what it does, it goes into each of them, and schedules them, but 
it first checks where the simulation is by looking up its little .db file, 
ie lambda1.1 simulation has a db which is empty, so it schedules it to run, but lambda 1.2 has already finished, 
and that's written in its DB, whereas lambda 1.3 has status "submitted" and therefore does not need to be 
submitted again, whereas lambda 1.5 has status "running" which also can be ignored. etc etc
"""

