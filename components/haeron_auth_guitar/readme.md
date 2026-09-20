# deploiement
```bash
helm install haeron-frontend-prod ./components/haeron_frontend \
  -f components/haeron_frontend/values_prod.yaml \
  -n haeron
```

# beta

```bash
helm install haeron-frontend-beta ./components/haeron_frontend \
  -f components/haeron_frontend/values_beta.yaml \
  -n haeron-beta
```

# Mise à jour (nouveau tag après un build CI)
```bash
helm upgrade haeron-frontend-prod ./components/haeron_frontend \
  -f components/haeron_frontend/values_prod.yaml \
  --set frontend.image.tag=prod-<sha> \
  -n haeron
```

Rappel important : le tag d'image seul ne suffit pas pour changer l'URL backend

Contrairement au backend où changer juste image.tag dans values_prod.yaml suffit (les vraies valeurs viennent des Secrets K8s au runtime), ici chaque tag d'image frontend correspond à un build précis avec une URL backend déjà figée dedans. Si tu changes l'URL du backend (nouveau domaine, par exemple), il faut rebuild l'image frontend avec le nouveau --build-arg, pas juste changer un values.yaml.

Vérification avant d'appliquer
```bash
helm template haeron-frontend-prod ./components/haeron_frontend \
  -f components/haeron_frontend/values_prod.yaml
```
Veux-tu qu'on enchaîne sur la mise à jour complète de la CI GitHub Actions pour ce frontend (le --build-arg selon la branche, comme vu précédemment), avec le bon repo et les bons noms de fichiers values_prod.yaml/values_beta.yaml ?