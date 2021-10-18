# TrRosetta-based protein hallucination
2021-10-18
Doug Tischer (dtischer at uw.edu)
Jue Wang (jue at post.harvard.edu)
Sidney Lisanza (lisanza at uw.edu)

This repository contains scripts for performing protein design by gradient
descent through the structure-prediction neural network TrRosetta. The method
is similar to that of [trDesign](https://github.com/gjoni/trDesign) except our
focus is generating scaffolds for functional motifs.

This code accompanies the paper:

    D. Tischer, S. Lisanza, J. Wang, R. Dong, I. Anishchenko, L. F. Milles, S. Ovchinnikov, D. Baker. Design of proteins presenting discontinuous functional sites using deep learning. (2020) bioRxiv, [doi:10.1101/2020.07.22.211482](https://www.biorxiv.org/content/10.1101/2020.11.29.402743v1).

## Requirements

`tensorflow` (tested on `1.14`)
`scwrl4` (optional, for sidechains. [download](http://dunbrack.fccc.edu/SCWRL3.php/))
`pyrosetta` (`2020.10+release.46415fa`, for obtaining structural models. see [pyrosetta.org](http://pyrosetta.org))

## Installation & Usage

Clone git repository:

    git clone https://github.com/dtischer/trdesign-motif.git

Run examples:

    cd example
    ./run_example.sh        # generates scaffold for PD-1 interface motif versus PD-L1
    ./run_example2.sh       # same task as above, but using a different trRosetta version (see below)

Fold design model from predicted pairwise distances & angles (first run the
example above, then run this in the `example` subfolder):

    sequence_design/fold.sh output/

Additional downstream analyses can be done using the scripts in `scoring/`.

## Contents

`hallucination`: contains hallucination script `design.py`. see code for full
list of command-line options.

`hallucination_grid`: an alternative hallucination script using a more recent
version of trRosetta. This version is slightly more accurate at structure
prediction, and also predicts the probability that some binned 3D position is
occupied by some other residue, in the reference frame of each residue.

`sequence_design`: scripts for folding design models from hallucinated pairwise
distances and angles (`fold.sh`) and for using Rosetta Fastdesign to design
better sequences onto the hallucinated backbones.

`scoring`: various scripts to compute metrics on the designs generated by the
hallucination script.

## Links

[trDesign](https://github.com/gjoni/trDesign) - free hallucination and fully constrained fixed-backbone sequence design using trRosetta
[trRosetta](https://github.com/gjoni/trRosetta) - protein structure prediction with a convolutional neural network
