# Crédits des sons

Covalence fournit huit sons, en plus de ceux du thème sonore du système. Ils ne sont pas sous la licence GPL de Covalence mais sous leur propre licence, libre. Les textes complets des licences sont dans `data/sounds/LICENSES/` (installés dans `share/covalence/sounds/LICENSES/`).

## Messages et notifications

| Nom dans Covalence | Fichier | Titre d'origine | Auteur | Licence |
|---|---|---|---|---|
| Rosée | `rosee.oga` | Tethys | The Android Open Source Project | Apache-2.0 |
| Envol | `envol.oga` | Ariel | The Android Open Source Project | Apache-2.0 |
| Vague | `vague.oga` | Salacia | The Android Open Source Project | Apache-2.0 |
| Carillon | `carillon.oga` | confirmation_002 | Kenney | CC0 1.0 |
| Cristal | `cristal.oga` | glass_001 | Kenney | CC0 1.0 |

## Sonneries

| Nom dans Covalence | Fichier | Titre d'origine | Auteur | Licence |
|---|---|---|---|---|
| Aurore | `aurore.oga` | Atria | The Android Open Source Project | Apache-2.0 |
| Orbite | `orbite.oga` | Ganymede | The Android Open Source Project | Apache-2.0 |
| Horizon | `horizon.oga` | Sedna | The Android Open Source Project | Apache-2.0 |

## Sources

- **Android Open Source Project** : dépôt `platform/frameworks/base`, dossier `data/sounds`, fichiers `notifications/material/ogg/Tethys.ogg`, `Ariel.ogg`, `Salacia.ogg` et `ringtones/material/ogg/Atria.ogg`, `Ganymede.ogg`, `Sedna.ogg`.
  https://android.googlesource.com/platform/frameworks/base/+/main/data/sounds
  Licence : Apache License 2.0, déclarée pour tout le dossier par `data/sounds/Android.bp` (`default_applicable_licenses: ["Android-Apache-2.0"]`). Vérifié le 27/09/2026.
- **Kenney, Interface Sounds 1.0** (créé le 11/02/2020) : fichiers `Audio/confirmation_002.ogg` et `Audio/glass_001.ogg`.
  https://kenney.nl/assets/interface-sounds
  Licence : Creative Commons Zero (CC0 1.0), indiquée sur la page et dans le `License.txt` du paquet. Vérifié le 27/09/2026. Le crédit n'est pas obligatoire, nous le donnons quand même.

## Modifications

Pour chaque son, en 2026 pour Covalence :

- silence de début et de fin coupé (seuil -50 dBFS) ;
- volume harmonisé : niveau moyen (RMS) à -20 dBFS, crête à -1,5 dBFS au plus ;
- rééchantillonné en 48 kHz stéréo et réencodé en Ogg Vorbis (qualité 0,5) ;
- renommé en français.

Durées : 0,3 à 1,4 s pour les sons de notification, 5 à 7,3 s pour les sonneries (jouées en boucle pendant un appel). Aucune sonnerie n'a été raccourcie.
