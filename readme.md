## Install Hashicorp Vault on Openshift:

- Kustomization to set-up an auto-unsealing [single Vault instance](overlays/epyc/kustomization.yaml) on Openshift.

- Can also deploy a [3-node HA Vault](3-node-cluster) cluster on Openshift.
  - Automatic Vault cluster initialization by using a initializer [job](components/vault-initializer) written in Python
  - Initializer job uses this [image](https://github.com/thikade/dockerfiles/blob/master/python). Basically any Python3 image with requests & kubernetes modules installed should suffice!
  - Auto-unseal not yet implemented (sorry!)

### Prereq


To download the remote Vault Helm chart, use:
```
$ helm repo add hashicorp  https://helm.releases.hashicorp.com
$ helm repo update
$ helm pull hashicorp/vault --version 0.29.1 --untar  --untardir base/charts/0.29.1
```

## Single Node Vault

### Install
```
$ kustomize build --enable-helm  overlays/epyc | oc apply -f -
```

## 3-node Vault cluster

### Install
```
$ kustomize build --enable-helm  3-node-cluster | oc apply -f -
```