#!/software/conda/envs/tensorflow/bin/python

##########################
## SUPRESS ALL WARNINGS ##
##########################
import warnings, logging, os
warnings.filterwarnings('ignore',category=FutureWarning)
logging.disable(logging.WARNING)
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import sys, subprocess, argparse, re
from subprocess import DEVNULL
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pylab as plt
import pickle

# imports for Ivan's contig search
from scipy import stats
import networkx as nx
from itertools import permutations

# directory of this script
script_dir = os.path.dirname(os.path.realpath(__file__))

####################
## load libraries ##
####################
from utils import *
from models import *
from to_pdb import *

def main(argv):
  p = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
  #-------------------------------------------------------------------------------------
  # Specifying the design task (args mostly used in this script)
  #-------------------------------------------------------------------------------------
  p.add_argument('--len', '-l',     default=None, type=str, help='''set length range for unconstrained design
    ex: 87-112''')
  p.add_argument('--num', '-n',     default=1, type=int, help='number of designs')
  p.add_argument('--pdb', '-p',     default=None, type=str, help='PDB for fixed backbone design')
  p.add_argument('--chain', '-c',   default=None, type=str, help='specify chain to use')
  p.add_argument('--cce_cutoff',    default=19.9, type=float, help='filter cce to CB ≤ x')
  p.add_argument('--mask', '-m',    default=None, type=str, help='''set positions to rebuild ['start-end:min-max,...']
  use 'start-end' to specify region to rebuild
  use 'min-max'   to specify length of indel
  ex: '10-15:0-5' replace pos. 10-15 with variable-loop of length 0-5
  ex: '10-15:5'   replace pos. 10-15 with fixed-loop of length 5
  ex: '10-15'     remove pdb cst. from positions 10 to 15
  ex: '10'        remove pdb cst. from position 10''')
  p.add_argument('--mask_v2', '-m2',    default=None, type=str, help='''set gap lengths between contigs of a refernce pdb
  use '<ch>start-end, min_insertion-max_insertion, <ch>start-end, min_insertion-max_insertion ...'
  ex: 'A12-24,2-5,A36-42,20-50,B6-11'
  You can reorder the contigs from the pdb too!
  ex: 'B6-11,9-21,A36-42,20-30,A12-24'
  Gaps and contigs can be in any sequence, though it only makes sense to alternate them
  ex: '10-20,B6-11,9-21,A36-42,20-30,A12-24,22-33'
  ''')
  p.add_argument('--min_gap',       default=0,    type=int, help='Minimum gap length with randomly placing contigs')
  p.add_argument('--stat_place',    default=False, type=str2bool, help='Contigs are randomly placed (preserving order) but do not move')
  p.add_argument('--spike',         default=0.0, type=float, help='initialize design from pdb seq')
  p.add_argument('--predict_loss',  default=None, type=str, help='predict losses for sequences in file (in fasta format)')
  p.add_argument('--seed_pdb',      default=None, type=str, help='a pdb that you would like to further design (just extracts sequence)')
  p.add_argument('--seed_seq',      default=None, type=str, help='a sequence (string) that you would like to further design')
  p.add_argument('--seed_msa',      default=None, type=str, help='a sequence (path to msa file) that you would like to further design')
  #-------------------------------------------------------------------------------------
  # Output options
  #-------------------------------------------------------------------------------------
  p.add_argument('--out', '-o',     default=None, type=str, help='filename prefix for output')
  p.add_argument('--save_img',      default=False, type=str2bool, help='save image of contact map')
  p.add_argument('--save_npz',      default=True, type=str2bool, help='save data for PyRosetta model building')
  p.add_argument('--save_pdb',      default=False, type=str2bool, help='use magic to quickly generate PDB structure')
  p.add_argument('--track_step',    default=None, type=int, help='save losses from trajectory every X steps')
  p.add_argument('--track_best',    default=False, type=str2bool, help='save intermediate features from best step. If set to False, a minimal .trb file is still output with contig indices and final losses.')
  p.add_argument('--scwrl',         default=False, type=str2bool, help='use scwrl to add sidechains [if --save_pdb]')
  p.add_argument('--force_contig_geo', default=False, type=str2bool, help='Replace hallucinated contig 6D predictions with 6D one-hot geometry of the reference pdb')
  #-------------------------------------------------------------------------------------
  # Graph setup kwargs (includes loss function terms)
  #-------------------------------------------------------------------------------------
  p.add_argument('--bin_width',     default='15_deg', type=str, help="What flavor trRosetta model to use. <'15_deg', '10_deg'> angle bins")
  p.add_argument('--seq_mode',      default='MSA', type=str, help="What do the logits represent? ['MSA','PSSM','SEQ']")
  p.add_argument('--feat_drop',     default=None, type=float, help='dropout rate for features')
  p.add_argument('--feat_drop_pdb', default=None, type=float, help='dropout rate for ij pairs that are part of a contig. Only compatible with mask_v2.')
  p.add_argument('--loss_pdb',      default=None, type=float, help='weight for pdb loss')
  p.add_argument('--loss_bkg',      default=None, type=float, help='weight for bkg loss')
  p.add_argument('--loss_eng',      default=None, type=float, help="weight for an 'energy' loss")
  p.add_argument('--loss_hbn',      default=None, type=float, help="weight for hbnet loss")
  p.add_argument('--loss_aa_comp',  default=None, type=float, help='weight for aa_comp loss')
  p.add_argument('--loss_aa_ref',   default=None, type=float, help='weight for aa_ref loss')
  p.add_argument('--loss_contacts', default=None, type=float, help='weight for regularizing the inv cov mat')
  p.add_argument('--loss_keep_out', default=None, type=float, help='weight for keep_out loss')
  p.add_argument('--cce_consist',   default=None, type=float, help="weight for triple consistency in Ivan's contig search")
  p.add_argument('--res_keep_out',  default=None, type=str, help='''residues for which nothing should be 'in front' of
  ex: binding site residues
  Note: These residues must be a subset of 'contigs' resiudes''')
  p.add_argument('--serial',        default=False, type=str2bool, help='enable approx. serial mode')
  p.add_argument('--n_models',      default=5, type=int, help='number of TrRosetta models to load into memory')
  p.add_argument('--specific_models', default=None, type=str, help="Load speicific trR models. ex:'xaa', 'xab',...")
  p.add_argument('--db_dir',      default=script_dir+'/../db/base_model/' , type=str, help='location of network weights and other databases')
  #-------------------------------------------------------------------------------------
  # Graph inputs (used at graph execution)
  #-------------------------------------------------------------------------------------       
  p.add_argument('--sample',        default=True, type=str2bool, help='Should sequence be sampled from logits?')
  p.add_argument('--seq_hard',      default=False, type=str2bool, help='Make input sequence one-hot before passing to trR')
  #-------------------------------------------------------------------------------------
  # Graph inputs (used at graph execution)
  #------------------------------------------------------------------------------------- 
  p.add_argument('--fix_N',         default=False, type=str2bool, help='fix the first contig to the N terminus. keep_order must be True')
  p.add_argument('--fix_C',         default=False, type=str2bool, help='fix the last contig to the N terminus. keep_order must be True')
  p.add_argument('--contigs',       default=None, type=str, help='''set (start, end) positions of PDB to KEEP
  use '<ch>start-end, <ch>start-end, ...'
  ex: B10-17,A22-29 to keep those contigs from PDB in that order''')
  p.add_argument('--hbnets',        default=None, type=str, help='''make a separate loss term for cce of this contig subset.
  Range specified same way as for the contigs. All residues must be a subset of the contigs
  ex: A10-10,A21-21,A34-34 to add a separate cce term for the geometry of residues A10,A21 and A34 in the reference pdb.''')
  p.add_argument('--keep_order',    default=False, type=str2bool, help='keep the order of the contigs as provided')
  p.add_argument('--cs_method',     default='dt', type=str, help="ContigSearch algorithm to use <'dt','ia','random'>")
  #-------------------------------------------------------------------------------------
  # MRF kwargs
  #-------------------------------------------------------------------------------------   
  p.add_argument('--lam',           default=4.5, type=float, help='')
  #-------------------------------------------------------------------------------------
  # Optimization settings
  #------------------------------------------------------------------------------------- 
  p.add_argument('--msa_num',       default=1000, type=int, help='number of sequences in MSA')
  p.add_argument('--rm_aa',         default=None, type=str, help='''disable specific amino acids from being sampled
  ex: 'C' or 'W,Y,F' ''')
  p.add_argument('--opt_method',    default='GD_constant', type=str, help="'GD_decay'/'GD_constant'/'MCMC'")
  p.add_argument('--opt_iter',      default=300, type=int, help='number of iterations')
  p.add_argument('--opt_rate',      default=0.2, type=float, help='(initial) learning rate')
  p.add_argument('--opt_decay',     default=2.0, type=float, help='decay exponent of GD opt')
  p.add_argument('--temp_soft_seq_decay', default=2.0, type=float, help='temp when sequence is kept soft')
  p.add_argument('--temp_soft_seq_min', default=1.0, type=float, help='min temp when sequence is kept soft')
  p.add_argument('--temp_soft_seq_max', default=1.0, type=float, help='max temp when sequence is kept soft')
  p.add_argument('--init_sd',       default=0.01, type=float, help='stdev of noise to add at logit initialization')
  p.add_argument('--keep_first',    default=False, type=str2bool, help='Keep order of seqs in MSA fixed')
  p.add_argument('--beta_i',        default=2.0, type=float, help='Initial beta factor for contig search')
  p.add_argument('--beta_f',        default=20.0, type=float, help='Final beta factor for contig search')
  #------------------------------------------------------------------------------------- 
  o = p.parse_args()

  ##########################################
  # Check for valid arguments
  ##########################################
  if o.out is None:
    err = f"ERROR: Output file not defined --out={o.out}"
    sys.exit(err)
  if o.pdb is None and o.len is None and o.predict_loss is None:
    err = f"ERROR: --pdb={o.pdb} or --len={o.len} or --len={o.predict_loss} must be defined "
    sys.exit(err)
  if (o.cs_method == 'ia') and ('-' in o.len):
    err = f"ERROR: Proteins must be a fixed length when using cs_method 'ia'"
    sys.exit(err)

  DB_DIR = o.db_dir # location of databases
  SCWRL = f"{DB_DIR}/scwrl4"                       # location of scwrl installation

  ##########################################
  # Dependent arguments
  ##########################################
  if o.contigs is not None and o.loss_pdb is None: o.loss_pdb = 1.0
  if o.contigs is not None and o.loss_bkg is None: o.loss_bkg = 1.0
  if o.hbnets is not None and o.loss_hbn is None: o.loss_hbn = 1.0
  if o.seq_mode == 'MSA' and o.feat_drop is None: o.feat_drop = 0.2
    
  if o.mask_v2 is not None and o.loss_pdb is None: o.loss_pdb = 1.0
  if o.mask_v2 is not None and o.loss_bkg is None: o.loss_bkg = 1.0
   
  print(o.__dict__)
    
  ##########################################
  # Independent arguments
  ##########################################
  kw_ContigSearch = {
    'fix_N': o.fix_N,
    'fix_C': o.fix_C,
    'keep_order': o.keep_order,
  }
  kw_hbnets = {}
  kw_MaskMode = {}
  kw_probe_bsite = {
    'bin_width': o.bin_width
  }
  kw_MRF = {
    'lam': o.lam,  
  }
  kw_graph_setup = {
    'seq_mode': o.seq_mode.upper(),
    'feat_drop': o.feat_drop,
    'loss_aa_comp': o.loss_aa_comp,
    'loss_aa_ref': o.loss_aa_ref,
    'loss_keep_out': o.loss_keep_out,
    'loss_hbn': o.loss_hbn,
    'loss_pdb': o.loss_pdb,
    'loss_bkg': o.loss_bkg,
    'loss_contigs': False if o.contigs is None else True,
    'cs_method': o.cs_method,
    'serial': o.serial, 
    'n_models': o.n_models,
    'specific_models': o.specific_models,
    'DB_DIR': DB_DIR,
    'kw_ContigSearch': kw_ContigSearch,
    'kw_MRF': kw_MRF,
    'kw_probe_bsite': kw_probe_bsite, # more entries are added below
    'kw_hbnets': kw_hbnets,
    'kw_MaskMode': kw_MaskMode,
  }
  graph_inputs_ = {
    'seq_hard': np.array([o.seq_hard]),
    'sample': np.array([o.sample]),
  }
  weights = {
    'pdb': o.loss_pdb,
    'bkg': o.loss_bkg,
    'hbn': o.loss_hbn,
    'eng': o.loss_eng,
    'aa_comp': o.loss_aa_comp,
    'aa_ref': o.loss_aa_ref,
    'keep_out': o.loss_keep_out,
    'contacts': o.loss_contacts,
  }
  kw_OptSettings = {
    'msa_num': o.msa_num,
    'rm_aa': o.rm_aa,
    'opt_method': o.opt_method,
    'opt_iter': o.opt_iter,
    'opt_rate': o.opt_rate,
    'opt_decay': o.opt_decay,
    'temp_soft_seq_decay': o.temp_soft_seq_decay,
    'temp_soft_seq_min': o.temp_soft_seq_min,
    'temp_soft_seq_max': o.temp_soft_seq_max,
    'init_sd': o.init_sd,
    'keep_first': o.keep_first,
    'beta_i': o.beta_i,
    'beta_f': o.beta_f,
    'graph_inputs': graph_inputs_,
    'weights': weights,
  }

  print(kw_graph_setup)
  
  ##########################################
  # Gather pdb geometries, bkg distributions
  ##########################################
  # extract pdb features
  if o.pdb is not None:
    print(f"extracting features from pdb={o.pdb}")
    if o.contigs is not None:
      chains = re.findall(r'[A-Z]', o.contigs)
      chains = list(set(chains))
    if o.mask_v2 is not None:
      chains = re.findall(r'[A-Z]', o.mask_v2)
      chains = list(set(chains))
    else:
      chains = o.chain
   
    pdb_out = prep_input(o.pdb, chain=chains)
    pdb_feat = pdb_out["feat"][None]
    desired_feat = np.copy(pdb_feat)
    kw_OptSettings['pdb_idx'] = pdb_out['pdb_idx']
    if o.contigs is not None:
      kw_ContigSearch["contigs"] = parse_contigs(o.contigs, pdb_out["pdb_idx"])
      kw_ContigSearch["ptn_geo"] = np.array(desired_feat[0], dtype=np.float32)
    
      # gather kw for ivan's contig search
      idx = cons2idxs(parse_contigs(o.contigs, pdb_out["pdb_idx"]))
      idx = np.array(idx)
      kw_probe_bsite['idx'] = idx
      kw_probe_bsite['bsite'] = pdb_out['feat'][idx[:,None], idx[None,:]]
    if o.hbnets is not None:
      kw_hbnets["contigs"] = parse_contigs(o.hbnets, pdb_out["pdb_idx"])
      kw_hbnets["ptn_geo"] = np.array(desired_feat[0], dtype=np.float32)
    if (o.mask_v2 is not None) and (o.hbnets is not None):
      mask_contigs = [el for el in o.mask_v2.split(',') if el[0].isalpha()]
      mask_contigs = ','.join(mask_contigs)
      kw_MaskMode['contigs'] = parse_contigs(mask_contigs, pdb_out["pdb_idx"])
    if (o.cs_method=='random') and (o.hbnets is not None):
      kw_MaskMode['contigs'] = parse_contigs(o.contigs, pdb_out["pdb_idx"])
    
    # spike in the pdb sequence
    seq_start = None
    if o.spike > 0:
      print(f"spiking in the sequence from pdb")
      pdb_seq = np.eye(21)[AA_to_N(pdb_out["seq"])]
      seq_start = o.spike * pdb_seq[None,None,:,:20]
      if o.msa_design:
        seq_start = np.tile(seq_start,[1,o.msa_num,1,1])

    # seeding the seq_start
    if o.seed_seq is not None:
      seq_start = np.eye(21)[AA_to_N(o.seed_seq)]
      if o.msa_design: seq_start = np.tile(seq_start,[1,msa_num,1,1])
    if o.seed_pdb is not None:
      seed_pdb_out = prep_input(o.pdb, chain=chains)
      seq_start = np.eye(21)[AA_to_N(seed_pdb_out["seq"])]
      if o.msa_design: seq_start = np.tile(seq_start,[1,msa_num,1,1])
    if o.seed_msa is not None:
      print('will impliment in the future')
    if o.seed_seq is not None or o.seed_pdb is not None or o.seed_msa is not None:
      graph_inputs_['I'] = seq_start
    
        
    # CCE cutoff
    if o.cce_cutoff is not None:
      pdb_dist = pdb_out["dist_ref"][None]
      mask_cce = np.logical_or(pdb_dist > o.cce_cutoff, pdb_dist < 1.0)
      desired_feat[mask_cce] = 0

    # setup moves (insertions/deletions)
    if o.mask is not None:
      L = pdb_feat.shape[1]
      moves, pdb_mask, min_L, max_L = mask_to_moves(o.mask,L)
      print(f"regions constrainted by the pdb {pdb_mask}")
    
  # background distributions
  if o.contigs is not None:
    if '-' in o.len:
      min_L, max_L = [int(n) for n in o.len.split('-')]
    else:
      min_L, max_L = int(o.len), int(o.len)
  elif o.mask_v2 is not None:
    min_L, max_L = 0,0
    for el in o.mask_v2.split(','):
      if el[0].isalpha(): 
        # adding a fixed length contig
        s,e = el[1:].split('-')
        s,e = int(s), int(e)
        min_L += e - s + 1
        max_L += e - s + 1
      else:
        # adding a variable length gap
        min,max = el.split('-')
        min,max = int(min), int(max)
        min_L += min
        max_L += max
  
  L_range = np.arange(min_L,max_L+1).tolist()
  if o.opt_method == "MCMC_biased":  bkg_padding = 20
  else: bkg_padding = 0
  bkg_range = np.arange(min_L-bkg_padding,max_L+bkg_padding+1).tolist()
  print(f"computing background distribution for {bkg_range[0]}-{bkg_range[-1]}")

  # ivan's method requires length during graph setup so it is a fixed single length
  kw_OptSettings['bkgs'] = get_bkg(bkg_range,DB_DIR=DB_DIR)
  kw_probe_bsite['L'] = int(L_range[0])  
  
  ##########################################
  # setup design model
  ##########################################
  print("setting up design model")
  model = mk_design_model(**kw_graph_setup)

  ##########################################
  # start design
  ##########################################
  # begin record file
  with open(f'{o.out}.txt', 'w') as outfile:
    outfile.write('#prefix total_loss loss length sequence\n')
    
  # save settings file
  with open(f"{o.out}.set","w") as outfile:
    outfile.write(f'{o.__dict__}\n')
    
  # read the checkpoint file, if it exists
  f_checkpoint = f'{o.out}.chkp'
  if os.path.exists(f_checkpoint):
    with open(f_checkpoint, 'r') as f_in:
      hals_done = f_in.read().splitlines()
      last_completed_hal = int(hals_done[-1]) if len(hals_done) != 0 else -1
      if last_completed_hal + 1 == o.num:
        print('All jobs have previously completed. There is nothing more to hallucinate.')
  else:
    last_completed_hal = -1
    
  for n in range(last_completed_hal + 1, o.num):
    if o.predict_loss is not None:
      ######################################
      # Predicting loss(es) from single sequence
      ######################################
      with open(o.predict_loss) as infile:
        while True:
          inputs = {'train': False}
          name = infile.readline().rstrip()
          seq_aa = infile.readline().rstrip()
          if not seq_aa: break  # break while loop if at end of the infile
          
          # seq to onehot
          seq = np.eye(20)[AA_to_N(list(seq_aa))]
          seq = np.transpose(seq, [1,0,2])
          inputs['I'] = seq[None]
          
          # select correct bkg
          L = seq.shape[-2]
          inputs['bkg'] = d_inputs['bkgs'][L][None]
          
          # weight losses
          weights={'pdb':2, 'bkg':1}
          weights_list = [weights.get(x,1) for x in model.loss_label]
          inputs['loss_weights'] = np.array(weights_list)[None]
          
          # predict losses
          grad, loss, feat, pssm, *ex_out_v = model.predict(inputs)
          to_save = {
            'loss': dict(zip(model.loss_label, loss[0])),
            'msa': N_to_AA(pssm.argmax(-1)[0,0]), 
            'acc': None
          }
          
          #save
          lines.append(save_result(to_save, f"{o.out}_{name.replace('>','')}", o))
    
    
    elif (o.contigs is not None) and (o.cs_method == 'dt'):
      ######################################
      # DOUG'S HYBRID BACKBONE DESIGN
      ######################################
      L = int(np.random.choice(L_range))
      print(f'Hallucinating protein of length {L}')
      kw_OptSettings['L_start'] = L

      output = model.design(**kw_OptSettings)

      # force contig geo
      if o.force_contig_geo:
        output['feat'] = force_contig_geo(output['feat'], pdb_out['feat'], output['track_best'])

      # record all input settings
      output['track_best']['settings'] = vars(o)  # converts values of obj attributes to dict

      save_result(output, f"{o.out}_{n}", o)

      
    elif (o.contigs is not None) and (o.cs_method == 'ia'):
      ######################################
      # IVAN'S HYBRID BACKBONE DESIGN
      ######################################
      L = kw_probe_bsite['L']
      print(f'Hallucinating protein of length {L}')
      kw_OptSettings['L_start'] = L
      print(f"kw_OptSettings['L_start']: {kw_OptSettings['L_start']}")

      output = model.design(**kw_OptSettings)

      # record all input settings
      output['track_best']['settings'] = vars(o)  # converts values of obj attributes to dict

      ##############
      # Calculate contig location
      ##############
      p2d_ = output['feat']
      bs_ij_ = output['track_best']['bsite_ij']
      bsite_nfrag = len(kw_ContigSearch['contigs'])
      NRES = L

      # fragment sizes and residue indices
      bsite = kw_probe_bsite['bsite']
      bsite_idx = kw_probe_bsite['idx']
      bsite_nres = bsite_idx.shape[0]
      j = np.cumsum([0]+[bsite_idx[i]>bsite_idx[i-1]+1 for i in range(1,bsite_nres)])
      fs = np.array([np.sum(j==i) for i in range(j[-1]+1)])
      fi = [np.where(j==i)[0] for i in range(j[-1]+1)]

      if False:
        print('p2d_', p2d_.shape, p2d_)
        print('bs_ij_', bs_ij_.shape, bs_ij_)
        print('bsite_nfrag', bsite_nfrag)
        print('NRES', NRES)
        print('bsite_idx', bsite_idx)
        print('bsite_nres', bsite_nres)
        print(j)
        print(fs)
        print(fi)

      # check binding site
      i2 = np.argsort(bs_ij_[0].flatten())[-(bsite_nfrag**2-bsite_nfrag):]
      G = nx.Graph()
      G.add_nodes_from([i for i in range(NRES)])
      G.add_edges_from([(i%NRES,i//NRES) for i in i2])
      max_clique_size = nx.algorithms.max_weight_clique(G,weight=None)[1]

      if max_clique_size > bsite_nfrag:
          max_clique_size = bsite_nfrag

      max_cliques = [c for c in nx.algorithms.enumerate_all_cliques(G) 
                     if len(c)==max_clique_size]

      print("bs size: %d out of %d"%(max_clique_size, bsite_nfrag), max_cliques)

      # enumerate all possible fragment orders and
      # identify the best scoring one
      trials = []
      for clique in max_cliques:
          for p in permutations(range(len(fs)),max_clique_size):
              p = np.array(p)
              a = np.hstack([np.arange(j)+i-(j-1)//2 for i,j in zip(clique,fs[p])])

              # skip if out of sequence range
              if np.sum(a<0)>0 or np.sum(a>=NRES)>0:
                  continue

              # skip if fragments clash
              if np.unique(a).shape[0]!=a.shape[0]:
                  continue

              b = np.hstack([fi[i] for i in p])

              P = p2d_[np.ix_(a,a.T)]
              Q = bsite[np.ix_(b,b.T)]
              s = np.mean(np.sum(-np.log(P)*Q,axis=-1))/4
              trials.append((s,a,b,p))

      trials.sort(key=lambda x: x[0])

      # add results to tracker
      trb = output['track_best']
      pdb_idx = kw_OptSettings['pdb_idx']
      if (len(trials) == 0) or (max_clique_size != bsite_nfrag):
        print('No motif matches could be found :(')
        trb['con_ref_idx0'] = kw_probe_bsite['idx'][None]
        trb['con_hal_idx0'] = None
        trb['con_ref_pdb_idx'] = [pdb_idx[idx0] for idx0 in trb['con_ref_idx0'][0]]
        trb['con_hal_pdb_idx'] = None
      else:
        best=trials[0]
        zscore = stats.zscore([t[0] for t in trials])[0]
        print("best: score= %.5f   zscore= %.5f   trials= %d   order="%(best[0],zscore,len(trials)), best[3])
        sys.stdout.flush()

        # order hal cons to match ref cons
        order = best[3]
        print('original ordering', best[1], order)
        best_cons = np.array(idxs2cons(best[1]))  # convert idx to con ranges
        best_cons_ordered = best_cons[np.argsort(order)]  # sort into the original contig order
        con_hal_idx0 = np.array(cons2idxs(best_cons_ordered))  # convert back to idxs
        print('new ordering', con_hal_idx0)

        trb['con_ref_idx0'] = kw_probe_bsite['idx'][None]  # spoof batch dim to be consistent
        trb['con_hal_idx0'] = con_hal_idx0[None]  # spoof batch dim to be consistent
        trb['con_ref_pdb_idx'] = [pdb_idx[idx0] for idx0 in trb['con_ref_idx0'][0]]  # [('A', 1)]
        trb['con_hal_pdb_idx'] = [('A', idx0+1) for idx0 in trb['con_hal_idx0'][0]]

      # force contig geo
      if o.force_contig_geo:
        output['feat'] = force_contig_geo(output['feat'], pdb_out['feat'], trb)

      # save results
      save_result(output, f"{o.out}_{n}", o)
          
        
    elif (o.mask_v2 is not None) or ((o.contigs is not None) and (o.cs_method=='random')):
      ######################################
      # Fixed contig placement methods
      ######################################
      if o.mask_v2 is not None:
        # apply the mask to the ref pdb features
        feat_hal, mappings = apply_mask(o.mask_v2, pdb_out)      
        
      elif o.cs_method=='random':
        print('Placing contigs randomly')
        # place contigs randomly
        feat_hal, mappings = scatter_contigs(o.contigs, pdb_out, L_range=o.len, keep_order=o.keep_order, min_gap=o.min_gap)
        
      # these are the pdb features we're trying to hallucinate
      graph_inputs_['pdb'] = feat_hal
      
      # note length
      L = feat_hal.shape[1]
      kw_OptSettings['L_start'] = L
      print(f'Hallucinating protein of length {L}')
      
      # info for hbnet CCE loss
      if o.loss_hbn is not None:
        graph_inputs_['con_hal_idx0'] = np.array(mappings['con_hal_idx0'])[None, None]  # spoof leading (batch, branch) dims
        
      if o.feat_drop_pdb is not None:
        mask_1d = mappings['mask_1d']  # (batch, L)
        mask_2d = mask_1d[:, :, None]*mask_1d[:, None, :]        
        graph_inputs_['pdb_mask_2d'] = mask_2d.astype(bool)
      
      # run model!
      output = model.design(**kw_OptSettings)
      
      # add contig mappings
      output['track_best'].update(mappings)

      # force contig geo
      if o.force_contig_geo:
        output['feat'] = force_contig_geo(output['feat'], pdb_out['feat'], output['track_best'])

      # record all input settings
      output['track_best']['settings'] = vars(o)  # converts values of obj attributes to dict

      save_result(output, f"{o.out}_{n}", o)
      
    else:
      print('PLEASE SPECIFY A DESIGN MODE')

    # record completed job numbers in the checkpoint file
    with open(f_checkpoint, 'a+') as f_out:
      f_out.write(f'{n}\n')

#################################################################################
def do_scwrl(inputs,ouputs):
  subprocess.run([f"{SCWRL}/Scwrl4","-i",inputs,"-o",ouputs], stdout=DEVNULL, stderr=DEVNULL)
  
def save_result(out, pre, o):
  # append to record file
  with open(f'{o.out}.txt', 'a') as outfile:
    seq, loss = out["msa"][0], out["loss"]
    print(seq)
    print(loss)
    total_loss = sum(loss.values())
    loss = str(loss).replace(" ","")
    line = f"{pre} {total_loss} {loss} {len(seq)} {seq}"
    print(line)
    outfile.write(line+'\n')
 
  # save tracker info
  if o.track_step is not None:
    with open(f'{pre}.trs', 'wb') as outfile:
      pickle.dump(out['track_step'], outfile)
  if o.track_best:
    with open(f'{pre}.trb', 'wb') as outfile:
      pickle.dump(out['track_best'], outfile)
  else: # output minimal tracker
    with open(f'{pre}.trb', 'wb') as outfile:
      trk = {k:out['track_best'][k] for k in ['con_ref_idx0', 'con_hal_idx0', 
                                              'con_ref_pdb_idx', 'con_hal_pdb_idx',
                                              'loss_nodrop', 'settings']}
      pickle.dump(trk, outfile)
      
  # save PDB
  if o.save_pdb:
    xyz, dm = feat_to_xyz(out["feat"])
    save_PDB(f"{pre}.pdb", xyz, dm, seq)
    if o.scwrl: do_scwrl(f"{pre}.pdb",f"{pre}.scwrl4.pdb")
    
  # save IMG (contact map)
  if o.save_img:
    plt.figure(figsize=(5,5))
    plt.imshow(split_feat(out["feat"])["dist"].argmax(-1))
    plt.savefig(f"{pre}.png", bbox_inches='tight')
    plt.close()
    
  # save NPZ (and single seq fas) for pyrosetta
  if o.save_npz:
    with open(f"{pre}.fas",'w') as fas:
      fas.write(f">{pre}\n{seq}\n")
    feats = split_feat(out["feat"])
    np.savez_compressed(f"{pre}.npz",**feats)
    
  # save MSA
  if len(out["msa"]) > 1:
    with open(f"{pre}.msa.fas",'w') as fas:
      for n,seq in enumerate(out["msa"]):
        fas.write(f">{pre}_{n}\n{seq}\n")
    
  return
#################################################################################
if __name__ == "__main__":
   main(sys.argv[1:])
