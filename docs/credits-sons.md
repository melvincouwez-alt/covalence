# Crédits des sons

Covalence fournit dix-neuf sons, en plus de ceux du thème sonore du système. Ils ne sont pas sous la licence GPL de Covalence mais sous leur propre licence, libre. Les textes complets des licences sont dans `data/sounds/LICENSES/` (installés dans `share/covalence/sounds/LICENSES/`).

## Messages et notifications

| Nom dans Covalence | Fichier | Titre d'origine | Auteur | Licence |
|---|---|---|---|---|
| Rosée | `rosee.oga` | Tethys | The Android Open Source Project | Apache-2.0 |
| Envol | `envol.oga` | Ariel | The Android Open Source Project | Apache-2.0 |
| Vague | `vague.oga` | Salacia | The Android Open Source Project | Apache-2.0 |
| Carillon | `carillon.oga` | confirmation_002 | Kenney | CC0 1.0 |
| Cristal | `cristal.oga` | glass_001 | Kenney | CC0 1.0 |
| Écho | `echo.oga` | Titan | The Android Open Source Project | Apache-2.0 |
| Duo | `duo.oga` | Carme | The Android Open Source Project | Apache-2.0 |
| Clochette | `clochette.oga` | Rhea | The Android Open Source Project | Apache-2.0 |
| Pop | `pop.oga` | pluck_001 | Kenney | CC0 1.0 |
| Bulle | `bulle.oga` | drop_002 | Kenney | CC0 1.0 |
| Givre | `givre.oga` | glass_005 | Kenney | CC0 1.0 |

## Sonneries

| Nom dans Covalence | Fichier | Titre d'origine | Auteur | Licence |
|---|---|---|---|---|
| Aurore | `aurore.oga` | Atria | The Android Open Source Project | Apache-2.0 |
| Orbite | `orbite.oga` | Ganymede | The Android Open Source Project | Apache-2.0 |
| Horizon | `horizon.oga` | Sedna | The Android Open Source Project | Apache-2.0 |
| Téléphone | `telephone.oga` | (création) | Covalence | CC0 1.0 |
| Écume | `ecume.oga` | Luna | The Android Open Source Project | Apache-2.0 |
| Brise | `brise.oga` | Umbriel | The Android Open Source Project | Apache-2.0 |
| Cascade | `cascade.oga` | Dione | The Android Open Source Project | Apache-2.0 |
| Carrousel | `carrousel.oga` | Callisto | The Android Open Source Project | Apache-2.0 |

## Sources

- **Android Open Source Project** : dépôt `platform/frameworks/base`, dossier `data/sounds`, fichiers `notifications/material/ogg/Tethys.ogg`, `Ariel.ogg`, `Salacia.ogg`, `Titan.ogg`, `Carme.ogg`, `Rhea.ogg` et `ringtones/material/ogg/Atria.ogg`, `Ganymede.ogg`, `Sedna.ogg`, `Luna.ogg`, `Umbriel.ogg`, `Dione.ogg`, `Callisto.ogg`.
  https://android.googlesource.com/platform/frameworks/base/+/main/data/sounds
  Licence : Apache License 2.0, déclarée pour tout le dossier par `data/sounds/Android.bp` (`default_applicable_licenses: ["Android-Apache-2.0"]`). Vérifié le 27/09/2026.
- **Kenney, Interface Sounds 1.0** (créé le 11/02/2020) : fichiers `Audio/confirmation_002.ogg`, `glass_001.ogg`, `pluck_001.ogg`, `drop_002.ogg` et `glass_005.ogg`.
  https://kenney.nl/assets/interface-sounds
  Licence : Creative Commons Zero (CC0 1.0), indiquée sur la page et dans le `License.txt` du paquet. Vérifié le 27/09/2026. Le crédit n'est pas obligatoire, nous le donnons quand même.
- **Téléphone** : sonnerie de téléphone à cloche synthétisée pour Covalence en 2026 (deux tons de 440 et 480 Hz frappés à 20 Hz, deux sonneries puis une pause). Versée dans le domaine public (CC0 1.0).

## Modifications

Pour chaque son repris, en 2026 pour Covalence :

- silence de début et de fin coupé (seuil -50 dBFS) ;
- volume harmonisé : niveau moyen (RMS) à -20 dBFS, crête à -1,5 dBFS au plus ;
- rééchantillonné en 48 kHz stéréo et réencodé en Ogg Vorbis (qualité 0,5) ;
- renommé en français.

Durées : 0,1 à 1,4 s pour les sons de notification, 3,3 à 10 s pour les sonneries (jouées en boucle pendant un appel). Cascade (Dione, 11,5 s) et Carrousel (Callisto, 12,8 s) ont été coupées à 10 s avec un fondu de 0,4 s ; les autres sonneries ne sont pas raccourcies.
