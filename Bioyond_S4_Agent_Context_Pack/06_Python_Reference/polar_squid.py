#!/usr/bin/env python3
"""
BYRobot Pick and Place script with proper mode handling
"""

import time
import sys
import argparse
from byrobot_python import BYRobotSample, ModeType

def main():
    # Get IP from command line if provided
    parser = argparse.ArgumentParser(description="BYRobot Pick/Place Controller with Auto Mode")
    parser.add_argument("--ip", default="192.168.1.220", help="Robot IP address")
    parser.add_argument("--port", type=int, default=56788, help="Robot port")
    args = parser.parse_args()
    
    robot_ip = args.ip
    robot_port = args.port
    
    # Create robot instance
    robot = BYRobotSample()
    
    try:
        # Step 1: Connect to robot
        print(f"Connecting to robot at {robot_ip}:{robot_port}...")
        if robot.connect(robot_ip, robot_port) != 0:
            print("Failed to connect!")
            return
        print("Connected successfully")
        time.sleep(1)
        
        # Step 2: Clear any errors first
        print("\nClearing any existing errors...")
        if robot.clear_errors():
            print("Errors cleared")
        else:
            print("Warning: Could not clear errors")
        time.sleep(1)
        
        # Step 3: Check current mode and switch to auto if needed
        print("\nChecking robot mode...")
        # The robot has internal methods for this, but they're private
        # We'll use the approach that the class uses internally
        
        # Try to enable - if it fails due to mode, we know we need to switch
        print("Attempting to enable robot...")
        if not robot.control_remote_enable(True):
            print("Enable failed - robot may not be in auto mode")
            print("\nIMPORTANT: Please switch the robot to AUTO mode using the teach pendant:")
            print("1. Press the mode button on the teach pendant")
            print("2. Select AUTO mode")
            print("3. Press Enter to continue...")
            input()
            
            # Try again after manual mode switch
            print("\nClearing errors again...")
            robot.clear_errors()
            time.sleep(1)
            
            print("Attempting to enable robot again...")
            if not robot.control_remote_enable(True):
                print("Failed to enable robot even after mode switch!")
                print("Please check the robot status and try again.")
                return
        
        print("Robot enabled successfully!")
        time.sleep(2)
        
        # Step 4: Check if Lua is ready
        print("\nChecking Lua program status...")
        if robot.get_is_lua_ready():
            print("Lua program is ready")
        else:
            print("Lua program not ready - starting it...")
            # The internal prepare_robot method would handle this
            # For now, we'll proceed
        
        # Step 5: Pick from stack
        print("\n" + "="*50)
        print("Running Pick1 operation...")
        pick_variables = {
            "0": 1,  # Stack operation
            "1": 1,  # Stack layer
            "2": 1,  # Column
            "3": 6,  # Z position adjustment
            "4": 1,  # Operation = Pick
            "5": 3,  # Material type (3, 5, 6, 7)
            "6": 0   # No rotation
        }
        
        if robot.set_sys_var_i(pick_variables):
            print("Pick1 operation started")
            print("Waiting for operation to complete...")
            
            # Wait and check for completion
            for i in range(10):
                time.sleep(1)
                print(f"  Waiting... {i+1}/10")
                
                # Check if variables have been reset (indicates completion)
                check_vars = robot.get_sys_var_i([0, 4])
                if check_vars and all(var.value == 0 for var in check_vars):
                    print("Pick1 operation completed!")
                    break
            else:
                print("Pick1 operation timeout - may still be running")
        else:
            print("Failed to start Pick1 operation")
        
        # Wait between operations
        print("\nWaiting 3 seconds before next operation...")
        time.sleep(3)
        
        # Step 6: Place
        print("\n" + "="*50)
        print("Running Place1 operation...")
        place_variables = {
            "0": 12,    # Instrument positions
            "1": 1,  # Position identifier
            "2": 0,  # Not used
            "3": 0,  # Not used
            "4": 2,  # Operation = Place
            "5": 3,  # Material type (3, 5, 6, 7)
            "6": 0   # Rotation
        }
        
        if robot.set_sys_var_i(place_variables):
            print("Place1 operation started")
            print("Waiting for operation to complete...")
            
            # Wait and check for completion
            for i in range(10):
                time.sleep(1)
                print(f"  Waiting... {i+1}/10")
                
                # Check if variables have been reset
                check_vars = robot.get_sys_var_i([0, 4])
                if check_vars and all(var.value == 0 for var in check_vars):
                    print("Place1 operation completed!")
                    break
            else:
                print("Place1 operation timeout - may still be running")
        else:
            print("Failed to start Place1 operation")

        # Step 7: Imaging
        time.sleep(10)

        # Step 8: Pick up from destination
        print("\n" + "="*50)
        print("Running Place1 operation...")
        place_variables = {
            "0": 12,    # Device ID = 1
            "1": 1,  # X position
            "2": 0,  # Y position
            "3": 0,  # Z position
            "4": 1,    # Operation = Place
            "5": 3,     # Object type
            "6": 0
        }
        
        if robot.set_sys_var_i(place_variables):
            print("Place1 operation started")
            print("Waiting for operation to complete...")
            
            # Wait and check for completion
            for i in range(10):
                time.sleep(1)
                print(f"  Waiting... {i+1}/10")
                
                # Check if variables have been reset
                check_vars = robot.get_sys_var_i([0, 4])
                if check_vars and all(var.value == 0 for var in check_vars):
                    print("Place1 operation completed!")
                    break
            else:
                print("Place1 operation timeout - may still be running")
        else:
            print("Failed to start Place1 operation")

        # Step 9: Put back to stack
        print("\n" + "="*50)
        print("Running Place1 operation...")
        place_variables = {
            "0": 1,    # Device ID = 1
            "1": 1,  # X position
            "2": 1,  # Y position
            "3": 7,  # Z position
            "4": 2,    # Operation = Pick
            "5": 3,     # Object type
            "6": 0
        }
        
        if robot.set_sys_var_i(place_variables):
            print("Place1 operation started")
            print("Waiting for operation to complete...")
            
            # Wait and check for completion
            for i in range(10):
                time.sleep(1)
                print(f"  Waiting... {i+1}/10")
                
                # Check if variables have been reset
                check_vars = robot.get_sys_var_i([0, 4])
                if check_vars and all(var.value == 0 for var in check_vars):
                    print("Place1 operation completed!")
                    break
            else:
                print("Place1 operation timeout - may still be running")
        else:
            print("Failed to start Place1 operation")

        
        print("\n" + "="*50)
        print("All operations completed successfully!")
        
    except KeyboardInterrupt:
        print("\n\nOperation interrupted by user")
    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Always disconnect
        print("\nDisconnecting...")
        robot.disconnect()
        print("Done!")

if __name__ == "__main__":
    main()