#!/bin/usr/env python3
"""
Overlay two molecule graphs.

Consider / fixme
 - scan the different molecules and find what would be the appropriate absolute/relative tolerance.
 It seems that absolute tolerance would be more meaningful in this case. Relative tolerance has the issue
 that it means a different thing: taking 10% of a very small charge is a very small value, and a very
 small tolerance. Look up the units and figure out how much the actual absolute tolerance should be taken into account.
"""

import networkx as nx
import MDAnalysis as mda
from os import path
import matplotlib.pyplot as plt
from overlay import *
# from rdkit import Chem


prefix = "/home/dresio/ucl/dataset/agastya_extracted/tyk2/l11-l14"
l11 = mda.Universe(path.join(prefix, 'init_l11.pdb'))
l14 = mda.Universe(path.join(prefix, 'final_l14.pdb'))

# read the corresponding charge values for the l14
l14_atoms, l14_bonds = get_charges(path.join(prefix, 'final_l14.ac'))
l11_atoms, l11_bonds = get_charges(path.join(prefix, 'init_l11.ac'))

# create graphs
# create the nodes and add edges for one ligand
l14_nodes = {}
for atomNode in l14_atoms:
    l14_nodes[atomNode.atomId] = atomNode
for nfrom, nto in l14_bonds:
    l14_nodes[nfrom].bindTo(l14_nodes[nto])

# create the nodes and add edges for the other ligand
l11_nodes = {}
for atomNode in l11_atoms:
    l11_nodes[atomNode.atomId] = atomNode
for nfrom, nto in l11_bonds:
    l11_nodes[nfrom].bindTo(l11_nodes[nto])

# overlay
print("About to overlay %d atoms with %d atoms" % (len(l14_nodes), len(l11_nodes)))
# 0.1 e charge has been used by default: Paper "Rapid, accurate" by Agastya et al
overlays = compute_overlays(l11_nodes.values(), l14_nodes.values(), rtol=0, atol=0.1)
# extract all the unique nodes from the pairs
all_matched_nodes = set()
for matched_pairs in overlays:
    print("Overlay found of len %d:" % len(matched_pairs))
    # print(matched_pairs)
    unique_nodes = []
    for pair in matched_pairs:
        unique_nodes.extend(list(pair))
    all_matched_nodes = all_matched_nodes.union(unique_nodes)

# extract the atoms that are appearing and disappearing
# the atom that appears has to be in G2 and not in any of the overlaps
appearing = [node for node in l14_nodes.values() if not node in all_matched_nodes]
print("appearing", appearing)
disappearing = [node for node in l11_nodes.values() if not node in all_matched_nodes]
print("disappearing", disappearing)

# CL2 has to be in disappearing

# check if you found the correct atoms. They should be a subset of the atoms picked by Agastya in his research
agastya_disapp_atoms = open(path.join(prefix, "disappearing_atoms.txt")).read().split()
agastya_app_atoms = open(path.join(prefix, "appearing_atoms.txt")).read().split()
#
for app_atom in appearing:
    isin = app_atom.atomName.lower() in [atom.lower() for atom in agastya_app_atoms]
    if not isin:
        print("An appearing atom not found in Agastya's list. Atom: ", app_atom.atomName)
for disapp_atom in disappearing:
    isin = disapp_atom.atomName.lower() in [dis_atom.lower() for dis_atom in agastya_disapp_atoms]
    if not isin:
        print("A disappearing atom not found in Agastya list. Atom: ", disapp_atom.atomName)

"""
In theory you have all the overlays. 
If some atom is not in any of the overlays, that means that it is a new atom that appears in one structure, 
but not in another. 
"""