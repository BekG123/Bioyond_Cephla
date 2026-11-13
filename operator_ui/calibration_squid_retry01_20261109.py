"""One operator-requested retry after the stationary vision timeout."""
import calibration_squid_20261109 as run

run.OUT = run.FOLDER / 'calibration_squid_retry01_20261109'
run.PLAN = run.FOLDER / 'calibration_squid_retry01_20261109_plan.json'
run.AUTH += (' Operator explicitly requested one retry after the first attempt '
             'timed out during stationary vision. Empty arm returned Home via '
             'the reviewed planner; setup and route unchanged.')

if __name__ == '__main__':
    run.main()
