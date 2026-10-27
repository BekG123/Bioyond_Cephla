"""Reuse the checked plate-relative trial with separate full7 evidence files."""
import argparse
from pathlib import Path
import trial_reseated_48well as trial

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-confirmed',action='store_true');args=parser.parse_args()
    trial.Path=Path
    trial.PROPOSAL=trial.FOLDER/'full7_reseat_adjustment_proposal_20261027.json'
    trial.PLAN=trial.FOLDER/'full7_reseat_authorized_trial_20261027.json'
    trial.RECORD=trial.FOLDER/'full7_reseat_open_claw_trial_20261027.json'
    original_save=trial.save
    trial.save=lambda name,data:original_save(name.replace('reseated_repeat1','full7_reseat'),data)
    trial.execute() if args.execute_confirmed else trial.prepare()

if __name__=='__main__':main()
