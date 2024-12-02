To include the remote vault helm chart into the kustomization locally,
use:
```
helm pull hashicorp/vault --version 0.29.1 --untar  --untardir base/charts/0.29.1
```