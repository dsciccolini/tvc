import json
import subprocess
import tempfile
import os
import datetime
import time
import sys
import re
import signal
import atexit

# Define RPC URLs for mainnet and testnet
RPC_URLS = {
    "um": [
        "https://api.mainnet-beta.solana.com",  # Primary RPC
        "https://mainnet.helius-rpc.com/?api-key=7eb219a8-779b-42fd-81af-ca59b203a52f"  # Backup RPC
    ],
    "ut": [
        "https://api.testnet.solana.com",  # Primary RPC
        "https://multi-muddy-model.solana-testnet.quiknode.pro/3c0cfe8cff3f4aa7c0903d2602fe82cba66f2bbd/"  # Backup RPC
    ]
}

# Define ranks to list
LIST_RANKS = [1, 25, 50, 75, 100, 200, 250, 300, 350, 400, 450, 500, 750, 1000]

# Debug mode toggle
DEBUG_MODE = False  # Set to False to automatically clean up files

# Flag to control the main loop
running = True

# Signal handler for graceful exit
def signal_handler(sig, frame):
    global running
    print("\n\033[1;33mGraceful shutdown initiated. Cleaning up...\033[0m")
    running = False

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Validate command-line arguments
if len(sys.argv) != 3:
    print("Usage: python3 tvc.py <um|ut> <validator_identity>")
    sys.exit(1)

cluster = sys.argv[1].lower()
validator_identity = sys.argv[2]

if cluster not in ["um", "ut"]:
    print("Error: First argument must be 'um' for mainnet or 'ut' for testnet.")
    sys.exit(1)

# Select appropriate RPC URLs
RPC_URLS = RPC_URLS[cluster]

def run_solana_command(command):
    """  Runs a Solana CLI command with multiple RPC endpoints for failover. Tries each RPC URL until one succeeds.   """
    for rpc_url in RPC_URLS:
        try:
            result = subprocess.run(
                command + ["--url", rpc_url, "--output", "json"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return result.stdout  # Successfully retrieved data, return it
        except subprocess.CalledProcessError as e:
            print(f"\033[1;31mWarning: RPC {rpc_url} failed ({e}). Trying next...\033[0m")

    print("\033[1;31mError: All RPC endpoints failed. Skipping this iteration.\033[0m")
    return None  # All RPCs failed, return None

def fetch_and_display_validator_data():
    """Fetches Solana validator data and prints rankings to the terminal."""

    # Create temporary files
    validators_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    sorted_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    ranked_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    validator_info_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    gossip_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")

    # Store temp file paths for cleanup in this function
    temp_files = [
        validators_file.name,
        sorted_file.name,
        ranked_file.name,
        validator_info_file.name,
        gossip_file.name
    ]

    try:
        # Fetch validator list
        validators_data = run_solana_command(["solana", "validators"])
        if not validators_data:
            # Clean up temp files before returning
            for file_path in temp_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
            return  # Skip this iteration if all RPCs failed

        # Save JSON output to file
        with open(validators_file.name, "w") as f:
            f.write(validators_data)

        validators = json.loads(validators_data).get("validators", [])

        # Fetch gossip data
        gossip_data = run_solana_command(["solana", "gossip"])
        if not gossip_data:
            # Clean up temp files before returning
            for file_path in temp_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
            return  # Skip this iteration if all RPCs failed

        # Save JSON output to file
        with open(gossip_file.name, "w") as f:
            f.write(gossip_data)

        gossip_data = json.loads(gossip_data)

        # Fetch validator info
        validator_info_data = run_solana_command(["solana", "validator-info", "get"])
        if not validator_info_data:
            # Clean up temp files before returning
            for file_path in temp_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
            return  # Skip if all RPCs failed

        with open(validator_info_file.name, "w") as f:
            f.write(validator_info_data)

        validator_info_data = json.loads(validator_info_data)

        # Sort validators by epochCredits
        sorted_validators = sorted(validators, key=lambda x: x.get("epochCredits", 0), reverse=True)

        # Add rank to validators with epochCredits > 0
        ranked_validators = [
            {**validator, "rank": idx + 1}
            for idx, validator in enumerate(sorted_validators) if validator.get("epochCredits", 0) > 0
        ]

        # Write sorted data to temp files
        with open(sorted_file.name, "w") as f:
            json.dump(sorted_validators, f, indent=2)

        with open(ranked_file.name, "w") as f:
            json.dump(ranked_validators, f, indent=2)

        # Retrieve Rank 1's epoch credits
        epoch_credits_rank_1 = ranked_validators[0]["epochCredits"] if ranked_validators else 0

        # Function to get validator name from identity pubkey
        def get_validator_name(validator_identity):
            for info in validator_info_data:
                if info.get("identityPubkey") == validator_identity:
                    return info.get("info", {}).get("name", "Unknown")
            return "Unknown"

        # Function to get validator's IP address from gossip data
        def get_ip_address(validator_identity):
            for node in gossip_data:
                if node.get("identityPubkey") == validator_identity:
                    return node.get("ipAddress", "Unknown")
            return "Unknown"

        # Function to get validator details from ranked_validators
        def get_validator_details(validator_identity):
            for validator in ranked_validators:
                if validator.get("identityPubkey") == validator_identity:
                    return {
                        "activatedStake": f"{int(validator.get('activatedStake', 0)) / 1_000_000_000:,.2f} ◎",
                        "version": validator.get("version", "Unknown"),
                        "skipRate": validator.get("skipRate", "Unknown")
                    }
            return {
                "activatedStake": "Unknown",
                "version": "Unknown",
                "skipRate": "Unknown"
            }

        # Clear terminal screen before each refresh
        os.system('clear')

        # Iterate over LIST_RANKS and print information for each validator
        for rank in LIST_RANKS:
            validator = next((v for v in ranked_validators if v["rank"] == rank), None)

            if validator:
                validator_identity = validator["identityPubkey"]
                validator_name = get_validator_name(validator_identity)
                epoch_credits = validator["epochCredits"]
                formatted_epoch_credits = f"{epoch_credits:,}"
                missed_credits = epoch_credits_rank_1 - epoch_credits
                formatted_missed_credits = f"{missed_credits:,}"
                validator_details = get_validator_details(validator_identity)
                ip_address = get_ip_address(validator_identity)

                # Print the information in the desired format
                print(
                    f"\033[1;36m--------------- | Validator TVC Tracker | --------------- \033[0m\n\n"
                )
                print(
                    f"\033[1;36mRank {rank:<4}\033[0m | Credits: {formatted_epoch_credits:<10} | Missed: {formatted_missed_credits:<10} | "
                    f"\033[1;36mIP:\033[0m {ip_address:<15} | \033[1;36mStake:\033[0m {validator_details['activatedStake']:<15} | \033[1;36mv\033[0m{validator_details['version']} | "
                    f"\033[1;36mValidator:\033[0m {validator_name:<30} | \033[1;36mIdentity:\033[0m {validator_identity:<44}"
                )
                print(
                    f"\n\nTimestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" +
                    f"\n\n\033[1;33mPress Ctrl+C to quit\033[0m"
                )
            else:
                print(f"Validator with rank {rank} not found in the current data.")

    finally:
        # Always clean up temp files unless in debug mode
        if not DEBUG_MODE:
            for file_path in temp_files:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as e:
                    print(f"\033[1;31mError removing temporary file {file_path}: {e}\033[0m")
        else:
            # Debug Mode: Keep temporary files
            print("\n\033[1;33mDebug Mode: Temporary files retained for inspection\033[0m")
            print(f"Validators File: {validators_file.name}")
            print(f"Sorted File: {sorted_file.name}")
            print(f"Ranked File: {ranked_file.name}")
            print(f"Validator Info File: {validator_info_file.name}")
            print(f"Gossip File: {gossip_file.name}")

# Main program
print("\033[1;33mStarting Validator TVC Tracker... Press Ctrl+C to quit.\033[0m")

try:
    while running:
        fetch_and_display_validator_data()

        # Sleep with interruption handling
        sleep_start = time.time()
        while running and time.time() - sleep_start < 5:
            time.sleep(0.1)  # Short sleep intervals to allow for quick response to signals
except KeyboardInterrupt:
    # This will be caught by the signal handler, but just in case:
    print("\n\033[1;33mGraceful shutdown initiated. Cleaning up...\033[0m")
    running = False

print("\033[1;32mValidator TVC Tracker has been shut down cleanly.\033[0m")