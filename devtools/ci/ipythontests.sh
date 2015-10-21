#!/bin/sh
# Run ipython notebook tests

cd examples/ipython
testfail=0
#python ipynbtest.py "sliced_sequential_ensembles.ipynb" || testfail=1
date
python ipynbtest.py "mstis_bootstrap.ipynb" || testfail=1
date
python ipynbtest.py "mstis.ipynb" || testfail=1
date
python ipynbtest.py "mstis_analysis.ipynb" || testfail=1
date
python ipynbtest.py "tutorial_pathmovers.ipynb" || testfail=1
date
python ipynbtest.py "repex_networks.ipynb" || testfail=1
date
python ipynbtest.py "mistis_setup.ipynb" || testfail=1
date
python ipynbtest.py "mistis_analysis.ipynb" || testfail=1
date
python ipynbtest.py "alanine.ipynb" || testfail=1
date
# needs to run after alanine since it need the trajectory.nc file
python ipynbtest.py "storage_tutorial.ipynb" || testfail=1
date
# python ipynbtest.py "visualization.ipynb" || testfail=1
cd ../..
if [ $testfail -eq 1 ]
then
    exit 1
fi

