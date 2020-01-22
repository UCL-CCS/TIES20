"""
Focuses on the _overlay function that actually traverses the molecule using the given starting points.
"""

from topology_superimposer import SuperimposedTopology, get_atoms_bonds_from_ac, \
    superimpose_topologies, _superimpose_topologies, assign_coords_from_pdb, \
    AtomNode, _overlay
import networkx as nx
from os import path
import numpy as np


def test_2diffAtoms_CN_wrongStart():
    """
    create a simple molecule chain with an ester
     LIGAND 1        LIGAND 2
        C1              C11
        \                \
        N1              N11
    In this there is only one solution.
    """
    # construct the LIGAND 1
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    n1 = AtomNode(name='N1', type='N')
    n1.set_coords(x=1, y=2, z=0)
    c1.bindTo(n1)

    # construct the LIGAND 2
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=1, y=1, z=0)
    n11 = AtomNode(name='N11', type='N')
    n11.set_coords(x=1, y=2, z=0)
    c11.bindTo(n11)

    # should return a list with an empty sup_top
    suptops = _overlay(c1, n11)
    # it should return an empty suptop
    assert len(suptops) == 1
    assert len(suptops[0]) == 0


def test_2diffAtoms_CN_rightStart():
    """
    Two different Atoms. Only one solution exists.

     LIGAND 1        LIGAND 2
        C1              C11
        \                \
        N1              N11
    """
    # construct the LIGAND 1
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    n1 = AtomNode(name='N1', type='N')
    n1.set_coords(x=1, y=2, z=0)
    c1.bindTo(n1)

    # construct the LIGAND 2
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=1, y=1, z=0)
    n11 = AtomNode(name='N11', type='N')
    n11.set_coords(x=1, y=2, z=0)
    c11.bindTo(n11)

    # should overlap 2 atoms
    suptops = _overlay(c1, c11)
    assert len(suptops) == 1
    suptop = suptops[0]

    # the number of overlapped atoms is two
    assert len(suptop) == 2
    correct_overlaps = [('C1', 'C11'), ('N1', 'N11')]
    for atomName1, atomName2 in correct_overlaps:
        assert suptop.contains_atomNamePair(atomName1, atomName2)

    # there is no other ways to traverse the molecule
    assert len(suptop.mirrors) == 0


def test_3diffAtoms_CNO_rightStart():
    """
    Only one solution exists.

     LIGAND 1        LIGAND 2
        C1              C11
        \                \
        N1              N11
        /                /
        O1              O11
    """
    # construct the LIGAND 1
    # ignore the third dimension
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    n1 = AtomNode(name='N1', type='N')
    n1.set_coords(x=1, y=2, z=0)
    c1.bindTo(n1)
    o1 = AtomNode(name='O1', type='O')
    o1.set_coords(x=1, y=3, z=0)
    o1.bindTo(n1)

    # construct the LIGAND 2
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=1, y=1, z=0)
    n11 = AtomNode(name='N11', type='N')
    n11.set_coords(x=1, y=2, z=0)
    c11.bindTo(n11)
    o11 = AtomNode(name='O11', type='O')
    o11.set_coords(x=1, y=3, z=0)
    o11.bindTo(n11)

    # should overlap 2 atoms
    suptops = _overlay(c1, c11)
    assert len(suptops) == 1
    suptop = suptops[0]

    # the number of overlapped atoms is two
    assert len(suptop) == 3
    correct_overlaps = [('C1', 'C11'), ('N1', 'N11'), ('O1', 'O11')]
    for atomName1, atomName2 in correct_overlaps:
        assert suptop.contains_atomNamePair(atomName1, atomName2)

    # no mirrors
    assert len(suptop.mirrors) == 0


def test_SimpleMultipleSolutions_rightStart():
    """
    A simple molecule chain with an ester.
    The ester allows for mapping (O1-O11, O2-O12) and (O1-O12, O2-O11)
    # fixme what if you start from the wrong O-O matching? should that be a case? how does
    comparies topologies would behave in that case?

     LIGAND 1        LIGAND 2
        C1              C11
        \                \
        N1              N11
        /\              / \
     O1    O2        O11   O12

    """
    # ignore the third coordinate dimension
    # construct the LIGAND 1
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    n1 = AtomNode(name='N1', type='N')
    n1.set_coords(x=1, y=2, z=0)
    c1.bindTo(n1)
    o1 = AtomNode(name='O1', type='O')
    o1.set_coords(x=1, y=3, z=0)
    o1.bindTo(n1)
    o2 = AtomNode(name='O2', type='O')
    o2.set_coords(x=2, y=3, z=0)
    o2.bindTo(n1)

    # construct the LIGAND 2
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=1, y=1, z=0)
    n11 = AtomNode(name='N11', type='N')
    n11.set_coords(x=1, y=2, z=0)
    c11.bindTo(n11)
    o11 = AtomNode(name='O11', type='O')
    o11.set_coords(x=1, y=3, z=0)
    o11.bindTo(n11)
    o12 = AtomNode(name='O12', type='O')
    o12.set_coords(x=2, y=3, z=0)
    o12.bindTo(n11)

    # should be two topologies
    suptops = _overlay(c1, c11)
    assert len(suptops) == 2

    # check if both representations were found
    # The ester allows for mapping (O1-O11, O2-O12) and (O1-O12, O2-O11)
    assert any(st.contains_atomNamePair('O1', 'O11') and st.contains_atomNamePair('O2', 'O12') for st in suptops)
    assert not all(st.contains_atomNamePair('O1', 'O11') and st.contains_atomNamePair('O2', 'O12') for st in suptops)
    assert any(st.contains_atomNamePair('O1', 'O12') and st.contains_atomNamePair('O2', 'O11') for st in suptops)
    assert not all(st.contains_atomNamePair('O1', 'O12') and st.contains_atomNamePair('O2', 'O11') for st in suptops)

    correct_overlaps = [('C1', 'C11'), ('N1', 'N11')]
    for st in suptops:
        for atomName1, atomName2 in correct_overlaps:
            assert st.contains_atomNamePair(atomName1, atomName2)

    # fixme - add a test case for the superimposer function that makes use of _overlay,
    # this is to resolve multiple solutions such as the one here


def test_2sameAtoms_2Cs_symmetry():
    """
    Two solutions with different starting points.

     LIGAND 1        LIGAND 2
        C1              C11
        \                \
        C2              C12
    """
    # construct the LIGAND 1
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    c2 = AtomNode(name='C2', type='C')
    c2.set_coords(x=1, y=2, z=0)
    c1.bindTo(c2)

    # construct the LIGAND 2
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=1, y=1, z=0)
    c12 = AtomNode(name='C12', type='C')
    c12.set_coords(x=1, y=2, z=0)
    c11.bindTo(c12)

    # should return a list with an empty sup_top
    suptops = _overlay(c1, c11)
    assert len(suptops) == 1
    assert suptops[0].contains_atomNamePair('C1', 'C11')
    assert suptops[0].contains_atomNamePair('C2', 'C12')

    suptops = _overlay(c1, c12)
    assert len(suptops) == 1
    assert suptops[0].contains_atomNamePair('C1', 'C12')
    assert suptops[0].contains_atomNamePair('C2', 'C11')


def test_mutation_separate_unique_match():
    """
    Two commponents separated by the mutation.

     LIGAND 1        LIGAND 2
        C1              C11
        |                |
        S1              O11
        |                |
        N1               N11
    """
    # construct the LIGAND 1
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    s1 = AtomNode(name='S2', type='S')
    s1.set_coords(x=2, y=1, z=0)
    c1.bindTo(s1)
    n1 = AtomNode(name='N1', type='N')
    n1.set_coords(x=3, y=1, z=0)
    n1.bindTo(s1)

    # construct the LIGAND 2
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=1, y=1, z=0)
    o11 = AtomNode(name='O11', type='O')
    o11.set_coords(x=2, y=1, z=0)
    c11.bindTo(o11)
    n11 = AtomNode(name='N11', type='N')
    n11.set_coords(x=3, y=1, z=0)
    n11.bindTo(o11)

    # should return a list with an empty sup_top
    suptops = _overlay(c1, c11)
    assert len(suptops) == 1
    assert suptops[0].contains_atomNamePair('C1', 'C11')

    suptops = _overlay(n1, n11)
    assert len(suptops) == 1
    assert suptops[0].contains_atomNamePair('N1', 'N11')


def test_mutation_separate_unique_match():
    """
    Two commponents separated by the mutation.

     LIGAND 1        LIGAND 2
        C1              C11
        |                |
        C2              C12
        |                |
        C3              O11
        |                |
        N1              N11
    """
    # construct the LIGAND 1
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    c2 = AtomNode(name='C2', type='C')
    c2.set_coords(x=2, y=1, z=0)
    c2.bindTo(c1)
    c3 = AtomNode(name='C3', type='C')
    c3.set_coords(x=2, y=1, z=0)
    c3.bindTo(c2)
    n1 = AtomNode(name='N1', type='N')
    n1.set_coords(x=3, y=1, z=0)
    n1.bindTo(c3)

    # construct the LIGAND 2
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=1, y=1, z=0)
    c12 = AtomNode(name='C12', type='C')
    c12.set_coords(x=2, y=1, z=0)
    c12.bindTo(c11)
    o11 = AtomNode(name='O11', type='O')
    o11.set_coords(x=3, y=1, z=0)
    o11.bindTo(c12)
    n11 = AtomNode(name='N11', type='N')
    n11.set_coords(x=3, y=1, z=0)
    n11.bindTo(o11)

    # should return a list with an empty sup_top
    suptops = _overlay(c1, c11)
    assert len(suptops) == 1
    assert suptops[0].contains_atomNamePair('C1', 'C11')

    suptops = _overlay(n1, n11)
    assert len(suptops) == 1
    assert suptops[0].contains_atomNamePair('N1', 'N11')


def test_3C_circle():
    """
    A circle should be detected.
    Many solutions (3 starting conditions, etc)

      LIGAND 1        LIGAND 2
         C1              C11
        /  \            /   \
      C2 - C3         C12 - C13
    """
    # construct the LIGAND 1
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    c2 = AtomNode(name='C2', type='C')
    c2.set_coords(x=1, y=2, z=0)
    c1.bindTo(c2)
    c3 = AtomNode(name='C3', type='C')
    c3.set_coords(x=2, y=2, z=0)
    c3.bindTo(c1)
    c3.bindTo(c2)

    # construct the LIGAND 2
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=1, y=1, z=0)
    c12 = AtomNode(name='C12', type='C')
    c12.set_coords(x=1, y=2, z=0)
    c11.bindTo(c12)
    c13 = AtomNode(name='C13', type='C')
    c13.set_coords(x=2, y=2, z=0)
    c13.bindTo(c11)
    c13.bindTo(c12)

    suptops = _overlay(c1, c11)
    # there are two solutions
    assert len(suptops) == 2
    assert any(st.contains_atomNamePair('C2', 'C12') and st.contains_atomNamePair('C3', 'C13') for st in suptops)
    assert any(st.contains_atomNamePair('C2', 'C13') and st.contains_atomNamePair('C3', 'C12') for st in suptops)
    # both solutions should have the same starting situation
    assert all(st.contains_atomNamePair('C1', 'C11') for st in suptops)
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)

    suptops = _overlay(c1, c12)
    assert len(suptops) == 2
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)

    suptops = _overlay(c1, c13)
    assert len(suptops) == 2
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)

    suptops = _overlay(c2, c11)
    assert len(suptops) == 2
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)

    suptops = _overlay(c2, c12)
    assert len(suptops) == 2
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)

    suptops = _overlay(c2, c13)
    assert len(suptops) == 2
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)

    suptops = _overlay(c3, c11)
    assert len(suptops) == 2
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)

    suptops = _overlay(c3, c12)
    assert len(suptops) == 2
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)

    suptops = _overlay(c3, c13)
    assert len(suptops) == 2
    # there should be one circle in each
    assert all(st.sameCircleNumber() for st in suptops)
    assert all(st.getCircleNumber() == (1, 1) for st in suptops)


def test_mcl1_l12l35():
    """
    Molecule inspired by Agastya's dataset (mcl1_l12l35).

    Ligand 1

         C1 - C2
         /      \
    Cl1-C3      C4
          \     /
          C5 - C6
          /     \
     C10-C7       N1
           \   /
             C8
             |
             C9


    Ligand 2
                 Cl11
                /
         C11 - C12
         /      \
        C13      C14
          \     /
          C15 - C16
          /     \
     C20-C17       N11
           \   /
             C18
             |
             C19
    """
    # construct LIGAND 1
    c1 = AtomNode(name='C1', type='C')
    c1.set_coords(x=1, y=1, z=0)
    c2 = AtomNode(name='C2', type='C')
    c2.set_coords(x=1, y=2, z=0)
    c1.bindTo(c2)
    c3 = AtomNode(name='C3', type='C')
    c3.set_coords(x=2, y=2, z=0)
    c3.bindTo(c1)
    cl1 = AtomNode(name='CL1', type='Cl')
    cl1.set_coords(x=2, y=1, z=0)
    cl1.bindTo(c3)
    c4 = AtomNode(name='C4', type='C')
    c4.set_coords(x=2, y=3, z=0)
    c4.bindTo(c2)
    c5 = AtomNode(name='C5', type='C')
    c5.set_coords(x=3, y=1, z=0)
    c5.bindTo(c3)
    c6 = AtomNode(name='C6', type='C')
    c6.set_coords(x=3, y=2, z=0)
    c6.bindTo(c5)
    c6.bindTo(c4)
    c7 = AtomNode(name='C7', type='C')
    c7.set_coords(x=4, y=2, z=0)
    c7.bindTo(c5)
    c10 = AtomNode(name='C10', type='C')
    c10.set_coords(x=4, y=1, z=0)
    c10.bindTo(c7)
    n1 = AtomNode(name='N1', type='N')
    n1.set_coords(x=4, y=3, z=0)
    n1.bindTo(c6)
    c8 = AtomNode(name='C8', type='C')
    c8.set_coords(x=5, y=1, z=0)
    c8.bindTo(c7)
    c8.bindTo(n1)
    c9 = AtomNode(name='C9', type='C')
    c9.set_coords(x=6, y=1, z=0)
    c9.bindTo(c8)

    # construct Ligand 2
    cl11 = AtomNode(name='Cl11', type='Cl')
    cl11.set_coords(x=1, y=1, z=0)
    c11 = AtomNode(name='C11', type='C')
    c11.set_coords(x=2, y=1, z=0)
    c12 = AtomNode(name='C12', type='C')
    c12.set_coords(x=2, y=2, z=0)
    c12.bindTo(c11)
    c12.bindTo(cl11)
    c13 = AtomNode(name='C13', type='C')
    c13.set_coords(x=3, y=1, z=0)
    c13.bindTo(c11)
    c14 = AtomNode(name='C14', type='C')
    c14.set_coords(x=3, y=2, z=0)
    c14.bindTo(c12)
    c15 = AtomNode(name='C15', type='C')
    c15.set_coords(x=4, y=1, z=0)
    c15.bindTo(c13)
    c16 = AtomNode(name='C16', type='C')
    c16.set_coords(x=4, y=2, z=0)
    c16.bindTo(c15)
    c16.bindTo(c14)
    c17 = AtomNode(name='C17', type='C')
    c17.set_coords(x=5, y=2, z=0)
    c17.bindTo(c15)
    c20 = AtomNode(name='C20', type='C')
    c20.set_coords(x=5, y=1, z=0)
    c20.bindTo(c17)
    n11 = AtomNode(name='N11', type='N')
    n11.set_coords(x=5, y=3, z=0)
    n11.bindTo(c16)
    c18 = AtomNode(name='C18', type='C')
    c18.set_coords(x=6, y=1, z=0)
    c18.bindTo(c17)
    c18.bindTo(n11)
    c19 = AtomNode(name='C19', type='C')
    c19.set_coords(x=7, y=1, z=0)
    c19.bindTo(c18)

    # the correct solution
    suptops = _overlay(c9, c19)
    assert len(suptops) == 1
    assert len(suptops[0]) == 11

    """
    This is a rare case around which we'll have to find a work around.
    Basically, the best solution that follows the basic traversal allows for a superimposition
    that should not be allowed. So additional additional way has to be checked to discredit it 
    """
    suptops = _overlay(c5, c14)
    assert len(suptops) == 1
    assert len(suptops[0]) != 12
