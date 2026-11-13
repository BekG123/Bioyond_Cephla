"""Second explicit operator-requested retry; unchanged checks and geometry."""
import calibration_squid_20261109 as run

run.OUT = run.FOLDER / 'calibration_squid_retry02_20261109'
run.PLAN = run.FOLDER / 'calibration_squid_retry02_20261109_plan.json'
run.AUTH += (' Operator explicitly requested another retry after the second '
             'stationary vision timeout. Same empty-gripper setup and clearance; '
             'reviewed Home return completed before calibration. No checks changed.')

if __name__ == '__main__':
    run.main()
