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
LIST_RANKS = [1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 
              150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800, 850, 900, 950, 
              1000, 1050, 1100, 1150, 1200, 1250, 1300]

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
        def get_validator_name(identity_pubkey):
            for info in validator_info_data:
                if info.get("identityPubkey") == identity_pubkey:
                    return info.get("info", {}).get("name", "Unknown")
            return "Unknown"

        # Function to get validator's IP address from gossip data
        def get_ip_address(identity_pubkey):
            for node in gossip_data:
                if node.get("identityPubkey") == identity_pubkey:
                    return node.get("ipAddress", "Unknown")
            return "Unknown"

        # Function to get validator details from ranked_validators
        def get_validator_details(identity_pubkey):
            for validator in ranked_validators:
                if validator.get("identityPubkey") == identity_pubkey:
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

        print(
            f"\033[1;32m------------------------- | Validator TVC Tracker | ------------------------- \033[0m\n"
        )

        # Ensure the user-provided validator_identity is included
        user_validator = next((v for v in ranked_validators if v["identityPubkey"] == validator_identity), None)
        if user_validator:
            user_validator_rank = user_validator["rank"]
            if user_validator_rank not in LIST_RANKS:
                LIST_RANKS.append(user_validator_rank)
                LIST_RANKS.sort()

        # Iterate over LIST_RANKS and print information for each validator
        for rank in LIST_RANKS:
            validator = next((v for v in ranked_validators if v["rank"] == rank), None)

            if validator:
                identity_pubkey = validator["identityPubkey"]
                validator_name = get_validator_name(identity_pubkey)
                epoch_credits = validator["epochCredits"]
                formatted_epoch_credits = f"{epoch_credits:,}"
                missed_credits = epoch_credits_rank_1 - epoch_credits
                formatted_missed_credits = f"{missed_credits:,}"
                validator_details = get_validator_details(identity_pubkey)
                ip_address = get_ip_address(identity_pubkey)

                # Print the information in the desired format
                # Limit the length of the validator_name to 30 characters
                if len(validator_name) > 25:
                    validator_name = validator_name[:22] + '...'

                if identity_pubkey == validator_identity:
                    color_code = "\033[1;32m"
                    reset_code = "\033[0m"
                    print(
                        f"{color_code}Rank {rank:<5} | Credits: {formatted_epoch_credits:<11} | Missed: {formatted_missed_credits:<9} | "
                        f"IP: {ip_address:<16} | Stake: {validator_details['activatedStake']:<17} | "
                        f"v{validator_details['version']:<13} | Validator: {validator_name:<25} | Identity: {identity_pubkey:<44}{reset_code}"
                    )
                else:
                    color_code = "\033[1;36m"
                    print(
                        f"{color_code}Rank\033[0m {rank:<5} | {color_code}Credits:\033[0m {formatted_epoch_credits:<11} | {color_code}Missed:\033[0m {formatted_missed_credits:<9} | "
                        f"{color_code}IP:\033[0m {ip_address:<16} | {color_code}Stake:\033[0m {validator_details['activatedStake']:<17} | " 
                        f"{color_code}v\033[0m{validator_details['version']:<13} | "
                        f"{color_code}Validator:\033[0m {validator_name:<25} | {color_code}Identity:\033[0m {identity_pubkey:<44}"
                    )
            else:
                print(f"Validator with rank {rank} not found in the current data.")
        print(
            f"\n\nTimestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" +
            f"\n\n\033[1;33mPress Ctrl+C to quit\033[0m"
        )

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