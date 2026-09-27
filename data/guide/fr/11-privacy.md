title: Vie privée
icon: preferences-system-privacy
summary: Ce que Covalence garde, où, et comment l'effacer.
---
Covalence fonctionne entièrement sur votre ordinateur. Son auteur n'exploite aucun serveur et ne reçoit aucune donnée : pas de compte Covalence, pas de télémétrie, pas de statistiques, pas de rapport de plantage envoyé.

## Données traitées
- Reçues de l'iPhone par Bluetooth : notifications, messages (texte, expéditeur, date), contacts, journal d'appels, état de la musique et de la batterie.
- Échangées directement avec Apple : courriel, agendas, rappels, contacts, fichiers et photos iCloud.

## Où elles sont gardées
- Cache des messages et des contacts : `~/.local/share/covalence/`, lisible par votre seul compte.
- Réglages : `~/.config/covalence/`. La configuration d'iCloud Drive y est chiffrée.
- Mots de passe et clés : le trousseau de votre session.
- Comptes iCloud : gérés par le système (Evolution Data Server).
- Les journaux de Covalence ne contiennent jamais le texte d'un message ni un numéro.

## Accès au réseau
En dehors d'iCloud, Covalence ne se connecte qu'à des services publics d'Apple, sans compte :
- icônes des apps de l'iPhone qui envoient des notifications : seul l'identifiant de l'app est envoyé (par exemple `net.whatsapp.WhatsApp`), jamais le contenu d'une notification. Cache : `~/.cache/covalence/app-icons/`. Pour couper : `app-icons=false` dans le groupe `[notifications]` de `~/.config/covalence/covalenced.conf` ;
- pochettes de la [lecture en cours](guide:sound) : seuls l'artiste et le titre sont envoyés. Cache : `~/.cache/covalence/artwork/`. Pour couper : `artwork=false` dans le groupe `[media]` du même fichier ;
- téléchargement de rclone, seulement quand vous le demandez.

## Tout effacer
1. Dans Services Apple, déconnectez iCloud Drive, iCloud Photos et le compte.
2. Supprimez les dossiers `~/.local/share/covalence/`, `~/.config/covalence/` et `~/.cache/covalence/`.
3. Dans l'app Mots de passe et clés, supprimez les entrées Covalence et iCloud.

Désinstaller le paquet ne supprime pas ces fichiers. Les messages et contacts de vos correspondants restent sous votre responsabilité : ne partagez pas ces dossiers.
