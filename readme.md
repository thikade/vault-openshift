## Install Hashicorp Vault on Openshift:
### Prereq
To update/replace the version of the remote vault Helm chart, download it to the kustomization locally.
```
$ helm pull hashicorp/vault --version 0.29.1 --untar  --untardir base/charts/0.29.1
```

### Verify
```
$ kustomize build --enable-helm  overlays/epyc
```

### Install
```
$ kustomize build --enable-helm  overlays/epyc | oc apply -f -
```