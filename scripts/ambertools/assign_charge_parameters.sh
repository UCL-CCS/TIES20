source ~/software/amber18install/amber.sh
# Log of work with Shunzhou

# todo - check if these are files with the right extension etc
LEFT=$1
RIGHT=$2

# update to eval rather than ``
CURRENT_DIR=`dirname $0`
cd $CURRENT_DIR
echo 'Current Dir' $CURRENT_DIR

# generate the mol2 topology
antechamber -i $LEFT -fi pdb -o left.mol2 -fo mol2 -c bcc -at gaff2 -nc {net_charge}
antechamber -i $RIGHT -fi pdb -o right.mol2 -fo mol2 -c bcc -at gaff2 -nc {net_charge}

# note that the charge -nc -1 so that you have to know the charges ahead
# QUESTION: is there an automatic charge detection? 
# this takes a minute or two
parmchk2 -i left.mol2 -o left.frcmod -f mol2 -s gaff2
parmchk2 -i right.mol2 -o right.frcmod -f mol2 -s gaff2
# this goes through the mol2 previously generated and adds any terms in the force field that are missing (angles, dihedrals, etc) 
# So we have now the terms and the charges and the bonds.
# The mol2 has the right atom type so that is directly connected the gaff2,
# whereas .frcmod has the extra terms.
# We have to merge the two properly and then run the simulation.

