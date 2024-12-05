import requests
import base64
import pprint
import time
import json
import re
from kubernetes import client, config
from kubernetes.stream import stream

# Configuration
VAULT_0_ADDRESS   = "http://vault-0.vault-internal.vault.svc:8200"

NAMESPACE = "vault"
POD_PRIMARY="vault-0"

SECRET_NAME = "vault-unseal-keys"        # Name of the Kubernetes Secret
SECRET_LABELS = {"app": "vault"}         # Optional: Labels for the secret


def vault_is_initialized(namespace, podname=POD_PRIMARY):
    response = exec_into_pod(k8s, NAMESPACE, podname, ["vault", "status", "-format=json"], silent=True)
    # Perform regex replacements for shitty Hashicorp json output
    response = re.sub(r"\'", "\"", response)
    response = re.sub(r":\s*True", ": true", response)
    response = re.sub(r":\s*False", ": false", response)
    json_response = json.loads(response)
    # pprint.pprint(json_response)
    return json_response["initialized"]


def vault_init(vault_address, secret_shares=5, secret_threshold=3):
    init_endpoint = f"{vault_address}/v1/sys/init"
    payload = {
        "secret_shares": secret_shares,
        "secret_threshold": secret_threshold
    }

    response = requests.post(init_endpoint, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error initializing Vault: {response.status_code} - {response.text}")


def vault_unseal(namespace, podname, unseal_keys):
    exec_into_pod(k8s, namespace, podname, ["vault", "operator", "unseal", unseal_keys[0]], silent=True)
    exec_into_pod(k8s, namespace, podname, ["vault", "operator", "unseal", unseal_keys[1]], silent=True)
    exec_into_pod(k8s, namespace, podname, ["vault", "operator", "unseal", unseal_keys[2]], silent=True)


def vault_status(namespace, podname):
    response = exec_into_pod(k8s, NAMESPACE, podname, ["vault", "status", "-format=json"], silent=True)
    # Perform regex replacements for shitty Hashicorp json output
    response = re.sub(r"\'", "\"", response)
    response = re.sub(r":\s*True", ": true", response)
    response = re.sub(r":\s*False", ": false", response)
    json_response = json.loads(response)
    # pprint.pprint(json_response)
    for key in ["cluster_name", "sealed", "initialized", "ha_enabled", "leader_cluster_address"]:
        print(f"{podname}  {key:>24}: {json_response[key]}")
    print()


def vault_cluster_peers(namespace, podname="vault-0"):
    exec_into_pod(k8s, namespace, podname, ["vault", "operator", "raft", "list-peers"])


def vault_join(k8s, namespace, podname, leader="vault-0"):
    exec_into_pod(k8s, namespace, podname, ["vault", "operator", "raft", "join", f"http://{leader}.vault-internal.vault.svc.cluster.local:8200"], silent=True)


def get_kubernetes_client():
    # Load Kubernetes configuration
    # config.load_kube_config()  # Use config.load_incluster_config() if running inside a pod
    config.load_incluster_config()

    # Kubernetes API client
    k8s = client.CoreV1Api()
    return k8s


def create_kubernetes_secret(k8s, namespace, secret_name, data, labels=None):
    secret_data = {key: base64.b64encode(value.encode()).decode() for key, value in data.items()}

    # pprint.pprint(secret_data)

    metadata = client.V1ObjectMeta(name=secret_name, namespace=namespace, labels=labels)
    secret = client.V1Secret(metadata=metadata, data=secret_data)

    # Create or update the secret
    try:
        existing_secret = k8s.read_namespaced_secret(secret_name, namespace)
        print(f"Updating existing secret: {secret_name}")
        secret.metadata.resource_version = existing_secret.metadata.resource_version
        k8s.replace_namespaced_secret(secret_name, namespace, secret)
    except client.exceptions.ApiException as e:
        if e.status == 404:  # Secret does not exist
            print(f"Creating new secret: {secret_name}")
            k8s.create_namespaced_secret(namespace, secret)
        else:
            raise


def exec_into_pod(k8s, namespace, pod_name, command, container_name=None, silent=False):
    # Execute command in the pod
    response = None
    try:
        response = stream(
            k8s.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=namespace,
            command=command,
            container=container_name,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        if not silent:
            print(f"Command Output:\n{response}")

    except client.exceptions.ApiException as e:
        print(f"Exception when executing command in pod: {e}")
    return response


def banner(message):
    # banner_length = len(message) + 4
    # print("#" * banner_length)
    print(f"### {message}")
    # print("#" * banner_length)


if __name__ == "__main__":
    try:
        k8s = get_kubernetes_client()

        banner("Checking whether Vault is already initialized...")
        initialized = vault_is_initialized(NAMESPACE, POD_PRIMARY)
        if initialized is True:
            print("Vault is already initialized. Exiting...")
            exit(0)
        elif initialized is False:
            pass
        else:
            print("Could not determine Vault initialization status.")
            exit(1)


        # Initialize Vault
        print("Initializing Vault...")
        init_response = vault_init(VAULT_0_ADDRESS)

        unseal_keys = init_response["keys_base64"]
        root_token = init_response["root_token"]
        print("Vault initialized successfully!")

        """DEBUG PRINT ONLY"""
        # pprint.pprint(init_response)

        # Prepare data for Kubernetes Secret
        secret_data = {
            "root_token": root_token
        }
        for index, value in enumerate(unseal_keys):
            secret_data.update({ f"UNSEAL_KEY_{index}": value })


        # Store in Kubernetes Secret
        print("Storing unseal keys and root token in Kubernetes Secret...")
        create_kubernetes_secret(
            k8s,
            namespace=NAMESPACE,
            secret_name=SECRET_NAME,
            data=secret_data,
            labels=SECRET_LABELS
        )
        print("Unseal keys and root token stored successfully.")

        banner(f"unseal {POD_PRIMARY}")
        vault_unseal(NAMESPACE, POD_PRIMARY, unseal_keys)

        banner(f"Login to primary pod '{POD_PRIMARY}'")
        exec_into_pod(k8s, NAMESPACE, POD_PRIMARY, ["vault", "login", root_token], silent=True)

        time.sleep(1)

        banner(f"join vault-1 to raft cluster")
        vault_join(k8s, NAMESPACE, "vault-1", leader=POD_PRIMARY)
        time.sleep(1)
        banner(f"unseal vault-1")
        vault_unseal(NAMESPACE, "vault-1", unseal_keys)
        time.sleep(1)

        banner(f"join vault-2 to raft cluster")
        vault_join(k8s, NAMESPACE, "vault-2", leader=POD_PRIMARY)
        time.sleep(1)
        banner(f"unseal vault-2")
        vault_unseal(NAMESPACE, "vault-2", unseal_keys)
        time.sleep(3)

        print()
        banner(f"VAULT CLUSTER STATUS:")
        vault_status(NAMESPACE, "vault-0")
        vault_status(NAMESPACE, "vault-1")
        vault_status(NAMESPACE, "vault-2")

        banner(f"List peers after join in pod '{POD_PRIMARY}' in namespace '{NAMESPACE}'...")
        vault_cluster_peers(NAMESPACE, POD_PRIMARY)

    except Exception as e:
        print(f"Error: {e}")
