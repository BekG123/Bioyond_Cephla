"""Single slow descent to the new taught destination; never releases."""
import descend_squid_20261103 as descent

if __name__ == '__main__':
    descent.SOURCE = descent.FOLDER/'destination_reteach_20261103T185217893840Z.json'
    descent.SHA = '7846a622f2cd4ebdc2ea0d518b95a06d9c184cb156c001dacf5f49b5b78b2a02'
    descent.APPROACH = descent.FOLDER/'loaded_trial_65a0371cb63c468fa7b527a1264cf610.json'
    descent.OUTPUT = descent.FOLDER/'slow_descent_20261103_from_65a0371c.json'
    descent.main()
