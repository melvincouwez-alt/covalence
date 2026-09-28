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

## Sécurité
- **Appairage** : rien n'est appairé sans votre clic sur **Le code correspond**. Pendant les trois minutes où l'ordinateur est visible, Covalence refuse les appairages sans code et n'accepte que les profils d'un iPhone (jamais un clavier ou une souris).
- **Autres programmes** : appeler, envoyer un message ou des fichiers, appairer, oublier l'iPhone, installer une mise à jour, supprimer ou modifier des données ne se fait sans question que depuis l'app Covalence. Si un autre programme le demande, une notification vous demande d'autoriser ou de refuser (refus sans réponse au bout d'une minute). Taper sur l'iPhone et confirmer un code d'appairage restent réservés à l'app.
- **Fichiers (LocalSend)** : chaque réception est demandée dans une notification, même depuis votre iPhone. Sur le réseau, rien ne prouve l'identité de l'expéditeur. Taille limitée à 20 Go par envoi, et jamais au point de remplir le disque.
- **Codes SMS dans le navigateur** : un code lié à un site par son SMS (`@exemple.fr #482913`) est rempli seul sur ce site et n'est jamais proposé ailleurs. Les autres codes demandent un clic sur la pastille, qui indique l'expéditeur du SMS. Pages HTTPS seulement.
- **Mises à jour** : le paquet est vérifié (SHA-256) une première fois après le téléchargement, puis de nouveau par le programme d'installation, sur une copie que seul l'administrateur peut modifier.
- **Recopie** : un code à quatre chiffres est demandé à l'iPhone à chaque démarrage.

## Tout effacer
1. Dans Services Apple, déconnectez iCloud Drive, iCloud Photos et le compte.
2. Supprimez les dossiers `~/.local/share/covalence/`, `~/.config/covalence/` et `~/.cache/covalence/`.
3. Dans l'app Mots de passe et clés, supprimez les entrées Covalence et iCloud.

Désinstaller le paquet ne supprime pas ces fichiers. Les messages et contacts de vos correspondants restent sous votre responsabilité : ne partagez pas ces dossiers.
