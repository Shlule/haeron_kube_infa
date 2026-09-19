# Déploiement infra Haeron — Guide d'initialisation complète

Ce document décrit la procédure complète pour déployer l'infrastructure Haeron
(Vault + Backend) sur un cluster Kubernetes (k3s) vierge.

## Prérequis

- Un cluster k3s fonctionnel avec accès `kubectl`
- Helm installé (`helm version`)
- Un Personal Access Token GitHub avec accès à `ghcr.io/shlule/haeron_backend_ecommerce`
- Les identifiants de connexion à la base de données Supabase (pooler, pas connexion directe)
- `htpasswd` installé (`sudo apt install apache2-utils` si absent)

---

## 0. Configuration de kubectl (à faire une seule fois par machine)

k3s protège son kubeconfig par défaut. Corriger les permissions et le rendre accessible :

```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(whoami):$(whoami) ~/.kube/config
export KUBECONFIG=~/.kube/config
kubectl get nodes   # doit afficher le nœud sans erreur
```

---

## 1. Créer le namespace

```bash
kubectl create namespace haeron
```

---

## 2. Déployer Vault

### 2.1 Appliquer la configuration Vault

```bash
kubectl apply -f components/haeron_vault/haeron-vault-prod.yaml
```

Ce fichier contient : ConfigMap (vault.hcl), ServiceAccount, RBAC, Services (vault + vault-internal), StatefulSet (3 replicas).

### 2.2 Attendre que `vault-0` démarre

```bash
kubectl get pods -n haeron -l app=vault -w
```

Le pod passe en `Running` mais reste `0/1 Ready` — **c'est normal**, Vault attend d'être initialisé.

### 2.3 Initialiser Vault (UNE SEULE FOIS dans la vie du cluster)

```bash
kubectl exec -it vault-0 -n haeron -- vault operator init -key-shares=5 -key-threshold=3
```

⚠️ **CRITIQUE** : sauvegarder immédiatement dans le gestionnaire de mots de passe de l'équipe :
- Les 5 clés de unseal
- Le root token initial

Ces valeurs ne sont affichées qu'une seule fois et ne sont récupérables nulle part ailleurs.

### 2.4 Unseal les 3 nœuds

```bash
for pod in vault-0 ; do
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-1>
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-2>
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-3>
done
```
```bash
for pod in vault-1 ; do
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-1>
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-2>
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-3>
done
```
```bash
for pod in vault-2 ; do
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-1>
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-2>
  kubectl exec -it $pod -n haeron -- vault operator unseal <clé-3>
done
```

### 2.5 Vérifier le cluster raft

```bash
kubectl get pods -n haeron -l app=vault --show-labels
```

Les 3 pods doivent être `1/1 Running`, avec `vault-sealed=false` sur les 3, et `vault-active=true` sur un seul d'entre eux (le leader).

### 2.6 Se connecter et activer le secret engine

```bash
kubectl exec -it vault-1 -n haeron -- vault login <root-token>
kubectl exec -it vault-1 -n haeron -- vault secrets enable -path=secret kv-v2
```

### 2.7 Créer la policy et le token dédiés au backend

```bash
kubectl exec -it vault-1 -n haeron -- vault policy write haeron-backend-policy - <<EOF
path "secret/data/haeron-backend" {
  capabilities = ["read"]
}
EOF

kubectl exec -it vault-1 -n haeron -- vault token create -policy=haeron-backend-policy -ttl=768h
```

⚠️ Sauvegarder ce token (différent du root token) — c'est celui qui ira dans le secret du backend, à l'étape 3.

---

## 3. Créer les secrets du backend

### 3.1 Secret GHCR (accès à l'image privée)

```bash
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=<ton-username-github> \
  --docker-password=<ton-token-github> \
  --docker-email=<ton-email> \
  -n haeron
```

### 3.2 ecrire un fichier d'env pour les secret. 

en suivant le .env.example ecrire un fichier et ensuite faire 

### 3.2 Secret applicatif (Vault + config)

```bash
kubectl create secret generic haeron-backend-secret \
--from-env-file=<nom_du_fichier>\
-n haeron
```

---
## 4. Déployer le backend (Helm)

### 4.1 adopt haeron namespace

```bash
kubectl label namespace haeron app.kubernetes.io/managed-by=Helm
kubectl annotate namespace haeron meta.helm.sh/release-name=haeron-prod
kubectl annotate namespace haeron meta.helm.sh/release-namespace=haeron
```

```bash
helm install haeron-prod ./components/haeron_backend \
  -f components/haeron_backend/values_prod.yaml \
  -n haeron
```

Pour l'environnement beta (dans son propre namespace) :

```bash
kubectl create namespace haeron-beta

kubectl get secret ghcr-secret -n haeron -o yaml | \
  sed 's/namespace: haeron$/namespace: haeron-beta/' | \
  kubectl apply -f -

kubectl get secret haeron-backend-secret -n haeron -o yaml | \
  sed 's/namespace: haeron$/namespace: haeron-beta/' | \
  kubectl apply -f -

kubectl patch secret haeron-backend-secret -n haeron-beta \
  --type='json' \
  -p='[{"op": "replace", "path": "/data/VAULT_ADDR", "value": "'$(echo -n "http://vault.haeron.svc.cluster.local:8200" | base64)'"}]'

htpasswd -nb <utilisateur> <mot-de-passe> > auth
kubectl create secret generic beta-basic-auth --from-file=auth -n haeron-beta

helm install haeron-beta ./components/haeron_backend \
  -f components/haeron_backend/values_beta.yaml \
  -n haeron-beta
```

---

## 5. Vérifications finales

```bash
kubectl get pods -n haeron
kubectl get pods -n haeron-beta
kubectl get ingress -n haeron -n haeron-beta
helm list -A
```

---

## 6. Lancer les migrations et le seed initial

```bash
kubectl exec -it <pod-backend> -n haeron -- uv run python src/manage.py migrate
kubectl exec -it <pod-backend> -n haeron -- uv run python src/manage.py createsuperuser
kubectl exec -it <pod-backend> -n haeron -- uv run python src/manage.py seed_db
```

---

## Commandes de maintenance courantes

| Action | Commande |
|---|---|
| Unseal après redémarrage d'un pod Vault | `kubectl exec -it <pod> -n haeron -- vault operator unseal <clé>` (x3) |
| État du cluster Vault | `kubectl get pods -n haeron -l app=vault --show-labels` |
| Accès UI Vault (port-forward) | `kubectl port-forward -n haeron pod/<leader> 8200:8200` |
| Mettre à jour le tag d'image (beta) | `helm upgrade haeron-beta ./components/haeron_backend -f components/haeron_backend/values_beta.yaml --set backend.image.tag=<tag> -n haeron-beta` |
| Rollback backend | `helm rollback haeron-prod <revision> -n haeron` |
| Régénérer le root token Vault (si compromis) | `vault operator generate-root -init` puis suivre la procédure (voir doc interne) |

---

## ⚠️ Sécurité — ne jamais commiter

- `.env.prod`, clés de unseal, root token Vault
- `cluster-issuer.yaml` (contient les identifiants API OVH) — utiliser `cluster-issuer.yaml.example` comme référence
- Tokens Vault backend (rotation recommandée tous les 32 jours, `ttl=768h`)