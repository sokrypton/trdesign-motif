#!/software/conda/envs/pyrosetta/bin/python3.7
import sys,os,json
import tempfile
import numpy as np

from arguments import *
from utils import *
from pyrosetta import *
from pyrosetta.rosetta.protocols.minimization_packing import MinMover

os.environ["OPENBLAS_NUM_THREADS"] = "1"

def main():

    ########################################################
    # process inputs
    ########################################################

    # read params
    scriptdir = os.path.dirname(os.path.realpath(__file__))
    with open(scriptdir + '/data/params.json') as jsonfile:
        params = json.load(jsonfile)

    # get command line arguments
    args = get_args(params)
    print(args)

    # init PyRosetta
    init('-hb_cen_soft -relax:default_repeats 5 -default_max_cycles 200 -out:level 100')

    # read and process restraints & sequence
    npz = np.load(args.NPZ)
    seq = read_fasta(args.FASTA)
    L = len(seq)
    params['seq'] = seq
    rst = gen_rst(npz,params)

    ########################################################
    # Scoring functions and movers
    ########################################################
    sf = ScoreFunction()
    sf.add_weights_from_file(scriptdir + '/data/scorefxn.wts')

    sf1 = ScoreFunction()
    sf1.add_weights_from_file(scriptdir + '/data/scorefxn1.wts')

    sf_vdw = ScoreFunction()
    sf_vdw.add_weights_from_file(scriptdir + '/data/scorefxn_vdw.wts')

    sf_cart = ScoreFunction()
    sf_cart.add_weights_from_file(scriptdir + '/data/scorefxn_cart.wts')

    mmap = MoveMap()
    mmap.set_bb(True)
    mmap.set_chi(False)
    mmap.set_jump(True)

    min_mover = MinMover(mmap, sf, 'lbfgs_armijo_nonmonotone', 0.0001, True)
    min_mover.max_iter(1000)

    min_mover1 = MinMover(mmap, sf1, 'lbfgs_armijo_nonmonotone', 0.0001, True)
    min_mover1.max_iter(1000)

    min_mover_vdw = MinMover(mmap, sf_vdw, 'lbfgs_armijo_nonmonotone', 0.0001, True)
    min_mover_vdw.max_iter(500)

    min_mover_cart = MinMover(mmap, sf_cart, 'lbfgs_armijo_nonmonotone', 0.0001, True)
    min_mover_cart.max_iter(1000)
    min_mover_cart.cartesian(True)

    repeat_mover = RepeatMover(min_mover, 3)
    
    ########################################################
    # initialize pose
    ########################################################
    pose0 = pose_from_sequence(seq, 'centroid' )

    # optional: make a poly_aa model
    if args.poly is not None:
      for i,_ in enumerate(seq):
        mutator = rosetta.protocols.simple_moves.MutateResidue(i+1, args.poly)
        mutator.apply(pose0)
      seq = pose0.sequence()
    
    # mutate GLY to ALA
    for i,a in enumerate(seq):
        if a == 'G':
            mutator = rosetta.protocols.simple_moves.MutateResidue(i+1,'ALA')
            mutator.apply(pose0)
            print('mutation: G%dA'%(i+1))

    set_random_dihedral(pose0)
    remove_clash(sf_vdw, min_mover_vdw, pose0)

    Emin = 99999.9
    
    ########################################################
    # minimization
    ########################################################

    for run in range(params['NRUNS']):

        pose = Pose()
        pose.assign(pose0)
        pose.remove_constraints()

        if run > 0:

            # diversify backbone
            dphi = np.random.uniform(-30,30,L)
            dpsi = np.random.uniform(-30,30,L)
            for i in range(1,L+1):
                pose.set_phi(i,pose.phi(i)+dphi[i-1])
                pose.set_psi(i,pose.psi(i)+dpsi[i-1])

            # remove clashes
            remove_clash(sf_vdw, min_mover_vdw, pose)

        if args.mode == 0:

            # short
            print('short')
            add_rst(pose, rst, 1, 12, params)
            repeat_mover.apply(pose)
            min_mover_cart.apply(pose)
            remove_clash(sf_vdw, min_mover1, pose)

            # medium
            print('medium')
            add_rst(pose, rst, 12, 24, params)
            repeat_mover.apply(pose)
            min_mover_cart.apply(pose)
            remove_clash(sf_vdw, min_mover1, pose)

            # long
            print('long')
            add_rst(pose, rst, 24, len(seq), params)
            repeat_mover.apply(pose)
            min_mover_cart.apply(pose)
            remove_clash(sf_vdw, min_mover1, pose)

        elif args.mode == 1:

            # short + medium
            print('short + medium')
            add_rst(pose, rst, 3, 24, params)
            repeat_mover.apply(pose)
            min_mover_cart.apply(pose)
            remove_clash(sf_vdw, min_mover1, pose)

            # long
            print('long')
            add_rst(pose, rst, 24, len(seq), params)
            repeat_mover.apply(pose)
            min_mover_cart.apply(pose)
            remove_clash(sf_vdw, min_mover1, pose)

        elif args.mode == 2:

            # short + medium + long
            print('short + medium + long')
            add_rst(pose, rst, 1, len(seq), params)
            repeat_mover.apply(pose)
            min_mover_cart.apply(pose)
            remove_clash(sf_vdw, min_mover1, pose)

        # check whether energy has decreased
        E = sf_cart(pose)
        if E < Emin:
            print("Energy(iter=%d): %.1f --> %.1f (accept)"%(run, Emin, E))
            Emin = E
            pose0.assign(pose)
        else:
            print("Energy(iter=%d): %.1f --> %.1f (reject)"%(run, Emin, E))


    # mutate ALA back to GLY
    for i,a in enumerate(seq):
        if a == 'G':
            mutator = rosetta.protocols.simple_moves.MutateResidue(i+1,'GLY')
            mutator.apply(pose0)
            print('mutation: A%dG'%(i+1))


    ########################################################
    # full-atom refinement
    ########################################################

    if args.fastrelax == True:

        sf_fa = create_score_function('ref2015')
        sf_fa.set_weight(rosetta.core.scoring.atom_pair_constraint, 5)
        sf_fa.set_weight(rosetta.core.scoring.dihedral_constraint, 1)
        sf_fa.set_weight(rosetta.core.scoring.angle_constraint, 1)

        mmap = MoveMap()
        mmap.set_bb(True)
        mmap.set_chi(True)
        mmap.set_jump(True)

        relax = rosetta.protocols.relax.FastRelax()
        relax.set_scorefxn(sf_fa)
        relax.max_iter(200)
        relax.dualspace(True)
        relax.set_movemap(mmap)

        pose0.remove_constraints()
        switch = SwitchResidueTypeSetMover("fa_standard")
        switch.apply(pose0)

        print('relax...')
        params['PCUT'] = 0.15
        add_rst(pose0, rst, 1, len(seq), params, True)
        relax.apply(pose0)

    ########################################################
    # fix backbone geometry
    ########################################################

        # idealize problematic local regions
        idealize = rosetta.protocols.idealize.IdealizeMover()
        poslist = rosetta.utility.vector1_unsigned_long()

        scorefxn=create_score_function('empty')
        scorefxn.set_weight(rosetta.core.scoring.cart_bonded, 1.0)
        scorefxn.score(pose0)

        emap = pose0.energies()
        print("idealize...")
        for res in range(1,L+1):
            cart = emap.residue_total_energy(res)
            if cart > 50:
                poslist.append(res)
                print( "idealize %d %8.3f"%(res,cart) )

        if len(poslist) > 0:
            idealize.set_pos_list(poslist)
        try:
            idealize.apply(pose0)

            # cart-minimize
            scorefxn_min=create_score_function('ref2015_cart')
            mmap.set_chi(False)

            min_mover = rosetta.protocols.minimization_packing.MinMover(mmap, scorefxn_min, 'lbfgs_armijo_nonmonotone', 0.00001, True)
            min_mover.max_iter(100)
            min_mover.cartesian(True)
            print("minimize...")
            min_mover.apply(pose0)

        except:
            print('!!! idealization failed !!!')


    ########################################################
    # save final model
    ########################################################
    pose0.dump_pdb(args.OUT)


if __name__ == '__main__':
    main()
