# we start the testing with the defined cases by Agastya,

from topology_superimposer import SuperimposedTopology, get_atoms_bonds_from_ac, \
    superimpose_topologies, _superimpose_topologies, assign_coords_from_pdb
import networkx as nx
import MDAnalysis as mda
from os import path


def get_problem(liglig_path):
    ligand_from, ligand_to = path.basename(liglig_path).split('-')
    hybrid_pair_path = path.join(liglig_path, "hybrid_par")
    print("working now on: ", hybrid_pair_path)
    # fixme - make sure these two are superimposed etc, that data is used later
    mda_left_lig = mda.Universe(path.join(hybrid_pair_path, 'init_%s.pdb' % ligand_from))
    mda_right_lig = mda.Universe(path.join(hybrid_pair_path, 'final_%s.pdb' % ligand_to))

    # read the corresponding charge values for the l14
    leftlig_atoms, leftlig_bonds = get_atoms_bonds_from_ac(path.join(hybrid_pair_path, 'init_%s.ac' % ligand_from))
    rightlig_atoms, rightlig_bonds = get_atoms_bonds_from_ac(path.join(hybrid_pair_path, 'final_%s.ac' % ligand_to))

    # fixme - make sure these two are superimposed etc, that data is used later
    # get the atom location using the .pdb which are superimposed onto each other
    assign_coords_from_pdb(leftlig_atoms, mda_left_lig)
    assign_coords_from_pdb(rightlig_atoms, mda_right_lig)

    # create graphs
    # create the nodes and add edges for one ligand
    # create the nodes and add edges for the other ligand
    ligand1_nodes = {}
    for atomNode in leftlig_atoms:
        ligand1_nodes[atomNode.get_id()] = atomNode
    for nfrom, nto in leftlig_bonds:
        ligand1_nodes[nfrom].bindTo(ligand1_nodes[nto])

    ligand2_nodes = {}
    for atomNode in rightlig_atoms:
        ligand2_nodes[atomNode.get_id()] = atomNode
    for nfrom, nto in rightlig_bonds:
        ligand2_nodes[nfrom].bindTo(ligand2_nodes[nto])

    return ligand1_nodes, ligand2_nodes


def test_mcl1_l18l39():
    # Agastya's cases
    liglig_path = "agastya_dataset/mcl1/l18-l39"
    lig1_nodes, lig2_nodes = get_problem(liglig_path)
    # we are ignoring the charges by directly calling the superimposer
    suptops = _superimpose_topologies(lig1_nodes.values(), lig2_nodes.values())
    # in this case, there should be only one solution
    assert len(suptops) == 1

    suptop = suptops[0]
    assert len(suptop) == 43

    # check the core atoms of the superimposition for correctness
    # this ensures that the atoms which have no choice (ie they can only be superimposed in one way)
    # are superimposed that way
    core_test_pairs = [('C21', 'C43'), ('C15', 'C37'), ('O3', 'O6'), ('C9', 'C31'),
                  ('C1', 'C23'), ('N1', 'N2'), ('C6', 'C28'), ('C4', 'C26')]
    for atomName1, atomname2 in core_test_pairs:
        assert suptop.contains_atomNamePair(atomName1, atomname2)

    # resolve the multiple possible matches
    avg_dst = suptop.correct_for_coordinates()

    # check if the mirrors were corrected
    corrected_symmetries = [('O2', 'O5'), ('O1', 'O4'), ('H7', 'H25'), ('H6', 'H24'),
                            ('H4', 'H22'), ('H5', 'H23'), ('H8', 'H26'), ('H9', 'H27')]
    for atomName1, atomname2 in corrected_symmetries:
        assert suptop.contains_atomNamePair(atomName1, atomname2)

    # refine against charges
    # ie remove the matches that change due to charge rather than spieces
    all_removed_pairs = suptop.refineAgainstCharges(atol=0.1)
    print(all_removed_pairs)
    removed_pairs = [('C5', 'C27'), ('C4', 'C26')]
    for atomName1, atomname2 in removed_pairs:
        assert not suptop.contains_atomNamePair(atomName1, atomname2)


def test_mcl1_l17l9():
    # Agastya's cases
    liglig_path = "agastya_dataset/mcl1/l17-l9"
    lig1_nodes, lig2_nodes = get_problem(liglig_path)

    suptops = _superimpose_topologies(lig1_nodes.values(), lig2_nodes.values())
    assert len(suptops) == 2

    for suptop in suptops:
        # the core chain should always be the same
        core_test_pairs = [('O3', 'O6'), ('C9', 'C28'), ('C3', 'C22'), ('C6', 'C25')]
        for atomName1, atomname2 in core_test_pairs:
            assert suptop.contains_atomNamePair(atomName1, atomname2)

    # use coordinates to solve multiple matches
    corrected_suptops = [st.correct_for_coordinates() for st in suptops]
    # sort according to the rmsd
    corrected_suptops.sort(key=lambda suptop: suptop.rmsd())
    solution_suptop = corrected_suptops[0]

    # check the core atoms of the superimposition for correctness
    # this ensures that the atoms which have no choice (ie they can only be superimposed in one way)
    # are superimposed that way
    multchoice_test_pairs = [('C18', 'C37'), ('O2', 'O4'),
                             ('O1', 'O5'), ('H10', 'H28'),
                             ('H9', 'H27'), ('H8', 'H26'),
                             ('H7', 'H25'), ('H6', 'H24'),
                             ('H5', 'H23')]
    for atomName1, atomname2 in multchoice_test_pairs:
        assert solution_suptop.contains_atomNamePair(atomName1, atomname2)

    # refine against charges
    # ie remove the matches that change due to charge rather than spieces
    all_removed_pairs = suptop.refineAgainstCharges(atol=0.1)
    print(all_removed_pairs)
    removed_pairs = [('C14', 'C33'), ('C15', 'C34'), ('C16', 'C35'), ('C17', 'C36')]
    for atomName1, atomname2 in removed_pairs:
        assert not suptop.contains_atomNamePair(atomName1, atomname2)

    # check if the lonely hydrogens were removed together with charges
    removed_lonely_hydrogens = [('H14', 'H32'), ('H11', 'H29')]
    for atomName1, atomname2 in removed_lonely_hydrogens:
        assert not suptop.contains_atomNamePair(atomName1, atomname2)
