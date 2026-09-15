# Exposer Vault en HTTPS via Ingress (optionnel)

Ce document décrit comment accéder à l'UI Vault via un nom de domaine et HTTPS,
plutôt que par `kubectl port-forward`. **Cette étape n'est pas indispensable**
au fonctionnement de l'infra — Vault et le backend fonctionnent parfaitement
sans elle.

## Prérequis

- L'infra de base doit déjà tourner (voir [README principal](../README.md)),
  Vault initialisé et unsealed
- Un nom de domaine chez OVH, avec accès à sa zone DNS
- `htpasswd` installé (`sudo apt install apache2-utils` si absent)

## Pourquoi cette approche (DNS-01, pas HTTP-01)

Si ta VM n'est pas accessible publiquement depuis internet (cas d'une VM
locale via VMware par exemple), le challenge HTTP-01 classique de Let's
Encrypt ne fonctionnera jamais. Le challenge **DNS-01** ne nécessite aucune
exposition publique : cert-manager valide la possession du domaine en créant
un enregistrement TXT directement via l'API OVH.

## Structure du Chart Helm utilisé dans ce document


---

## 1. Installer cert-manager

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.3/cert-manager.yaml
```

Vérifier que les pods démarrent correctement :
```bash
kubectl get pods -n cert-manager
```

---

## 2. Installer le webhook OVH

```bash
helm repo add cert-manager-webhook-ovh-charts https://aureq.github.io/cert-manager-webhook-ovh/
helm repo update

helm install cert-manager-webhook-ovh cert-manager-webhook-ovh-charts/cert-manager-webhook-ovh \
  --namespace cert-manager \
  --set groupName='acme.haeron.local'
```

⚠️ Note la valeur de `groupName` choisie ici — elle doit être réutilisée
**identique** dans le `values.yaml` du Chart à l'étape 4.

---

## 3. Créer un token API OVH

Sur https://api.ovh.com/createToken/, créer un token avec les droits suivants
(remplacer `tondomaine.com` par ton vrai domaine) :



Choisir une validité **"Unlimited"** — ce token est utilisé pour un
renouvellement automatique périodique (tous les ~60 jours) ; un token à durée
limitée finirait par expirer silencieusement et casser le renouvellement.

Récupérer les 3 valeurs générées : `Application Key`, `Application Secret`,
`Consumer Key`.

### Créer le secret Kubernetes correspondant

```bash
kubectl create secret generic ovh-credentials \
  --from-literal=applicationKey=<ta-clé> \
  --from-literal=applicationSecret=<ton-secret> \
  --from-literal=consumerKey=<ta-consumer-key> \
  -n cert-manager
```

⚠️ Ce secret n'est jamais versionné — il vit uniquement dans le cluster et
dans le gestionnaire de mots de passe de l'équipe.

---

## 4. Créer le Chart Helm `vault-ingress`

### `Chart.yaml`

```yaml
apiVersion: v2
name: vault-ingress
description: Ingress HTTPS + ClusterIssuer pour l'UI Vault
type: application
version: 0.1.0
```

### `values.yaml` (commité — placeholders uniquement)

```yaml
namespace: haeron

vault:
  host: vault.haeron-music.com

acme:
  email: <TON_EMAIL>
  groupName: acme.haeron.local
```

### `values-secret.yaml.example` (commité, sert de référence)

```yaml
acme:
  email: <TON_EMAIL>
```

### `values-secret.yaml` (à créer localement, JAMAIS commité)

```bash
cp vault-ingress/values-secret.yaml.example vault-ingress/values-secret.yaml
# éditer values-secret.yaml : renseigner le vrai email
```

Ajouter au `.gitignore` :

vault-ingress/values-secret.yaml


### `templates/cluster-issuer.yaml`

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns-ovh
spec:
  acme:
    email: {{ .Values.acme.email }}
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-dns-ovh-key
    solvers:
      - dns01:
          webhook:
            groupName: {{ .Values.acme.groupName }}
            solverName: ovh
            config:
              endpoint: ovh-eu
              applicationKeySecretRef:
                key: applicationKey
                name: ovh-credentials
              applicationSecretRef:
                key: applicationSecret
                name: ovh-credentials
              consumerKeySecretRef:
                key: consumerKey
                name: ovh-credentials
```

### `templates/certificate.yaml`

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: vault-tls
  namespace: {{ .Values.namespace }}
spec:
  secretName: vault-tls-secret
  issuerRef:
    name: letsencrypt-dns-ovh
    kind: ClusterIssuer
  dnsNames:
    - {{ .Values.vault.host }}
```

### `templates/middleware.yaml`

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: vault-auth
  namespace: {{ .Values.namespace }}
spec:
  basicAuth:
    secret: vault-basic-auth
```

### `templates/ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: vault-ui
  namespace: {{ .Values.namespace }}
  annotations:
    traefik.ingress.kubernetes.io/router.middlewares: {{ .Values.namespace }}-vault-auth@kubernetescrd
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - {{ .Values.vault.host }}
      secretName: vault-tls-secret
  rules:
    - host: {{ .Values.vault.host }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: vault
                port:
                  number: 8200
```

---

## 5. Créer le Basic Auth (protection avant la page de login Vault)

```bash
htpasswd -nb <utilisateur> <mot-de-passe> > auth
kubectl create secret generic vault-basic-auth --from-file=auth -n haeron
```

Pour ajouter d'autres personnes autorisées :
```bash
htpasswd -nb utilisateur1 motdepasse1 > auth
htpasswd -nb utilisateur2 motdepasse2 >> auth
kubectl create secret generic vault-basic-auth --from-file=auth -n haeron
```

---

## 6. Vérifier le rendu avant d'appliquer

```bash
helm template vault-ingress ./vault-ingress \
  -f vault-ingress/values.yaml \
  -f vault-ingress/values-secret.yaml
```

Vérifie que l'email et le host affichés sont corrects.

---

## 7. Déployer le Chart

```bash
helm install vault-ingress ./vault-ingress \
  -f vault-ingress/values.yaml \
  -f vault-ingress/values-secret.yaml \
  -n haeron
```

### Vérifier que le ClusterIssuer est accepté

```bash
kubectl describe clusterissuer letsencrypt-dns-ovh
```

Chercher dans `Status > Conditions` : `Type: Ready`, `Status: True`.

### Vérifier la progression du certificat

```bash
kubectl get certificate -n haeron -w
```

Attendre `READY: True`. Si ça bloque plus de 2-3 minutes, voir la section
Dépannage plus bas.

---

## 8. Résolution DNS locale (VM non exposée publiquement)

Ajouter sur la machine hôte (celle qui ouvre le navigateur) :

**Windows** — `C:\Windows\System32\drivers\etc\hosts` :



---

## 9. Tester

### En ligne de commande d'abord

```bash
curl -v -u <utilisateur>:<mot-de-passe> https://vault.haeron-music.com
```

Doit renvoyer le HTML de la page de login Vault.

### Dans le navigateur

https://vault.haeron-music.com


1. Popup Basic Auth → entrer les identifiants créés à l'étape 5
2. Cadenas HTTPS valide (certificat Let's Encrypt réel)
3. Page de login Vault → authentification par token

---

## Mettre à jour la config (nouveau host, nouvel email, etc.)

```bash
helm upgrade vault-ingress ./vault-ingress \
  -f vault-ingress/values.yaml \
  -f vault-ingress/values-secret.yaml \
  -n haeron
```

---

## Dépannage

| Symptôme | Vérifier |
|---|---|
| `ClusterIssuer` reste non-Ready | `kubectl describe clusterissuer letsencrypt-dns-ovh` — souvent un problème de credentials OVH ou de `groupName` mal aligné |
| `Certificate` reste `READY: False` | `kubectl get challenge -n haeron` puis `kubectl describe challenge -n haeron <nom>` |
| Erreurs côté webhook OVH | `kubectl logs -n cert-manager -l app=cert-manager-webhook-ovh -f` |
| `curl` échoue en TLS | Vérifier que le secret `vault-tls-secret` existe : `kubectl get secret vault-tls-secret -n haeron` |
| `401 Unauthorized` sans popup navigateur | Vérifier l'annotation `router.middlewares` sur l'Ingress, et que le Middleware existe bien dans le bon namespace |

---

## Maintenance

- Le certificat Let's Encrypt est renouvelé automatiquement par cert-manager
  (~30 jours avant expiration, certificat valide 90 jours)
- Le token OVH doit être configuré en validité **illimitée** pour ne pas
  casser ce renouvellement automatique
- En cas de rotation du token OVH, mettre à jour le secret :
```bash
  kubectl create secret generic ovh-credentials \
    --from-literal=applicationKey=<nouvelle-clé> \
    --from-literal=applicationSecret=<nouveau-secret> \
    --from-literal=consumerKey=<nouvelle-consumer-key> \
    -n cert-manager \
    --dry-run=client -o yaml | kubectl apply -f -