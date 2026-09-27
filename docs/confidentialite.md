# Confidentialité

Covalence fonctionne entièrement sur votre ordinateur. Son auteur n'exploite aucun serveur et ne
reçoit aucune donnée : pas de compte Covalence, pas de télémétrie, pas de statistiques d'usage, pas
de rapport de plantage envoyé.

## Données traitées

- Reçues de l'iPhone par Bluetooth : notifications, messages SMS et iMessage (texte, expéditeur,
  date), contacts et leurs photos, journal d'appels, état de la musique et de la batterie.
- Échangées directement avec les serveurs d'Apple : courriel, agendas, rappels et contacts iCloud,
  fichiers iCloud Drive et photos iCloud Photos.
- Écouteurs AirPods : batterie, réglages et nom, lus par Bluetooth.

## Où elles sont stockées

| Données | Emplacement |
|---|---|
| Messages, contacts de l'iPhone, photos des contacts, journal d'appels, brouillons | `~/.local/share/covalence/messages/` (dossier 0700, fichiers 0600, lisibles par votre seul compte) |
| Notifications de l'iPhone | en mémoire seulement, jamais écrites sur disque |
| Réglages (modules, choix par application, écouteurs) | `~/.config/covalence/` |
| Configuration d'iCloud Drive et Photos | `~/.config/covalence/rclone.conf`, chiffrée par rclone |
| Cache des fichiers iCloud Drive et Photos | `~/.cache/rclone/` (cache de rclone, 5 Go et 7 jours au plus par défaut, réglable) |
| Mots de passe et clé de chiffrement | trousseau de votre session (GNOME Keyring) |
| Comptes iCloud (courriel, agendas, contacts) | Evolution Data Server : `~/.config/evolution/sources/`, cache dans `~/.cache/evolution/` et `~/.local/share/evolution/` |

Les journaux de Covalence (`journalctl --user -u covalenced`) enregistrent des événements et des
nombres, jamais le texte d'un message, un nom ou un numéro.

## Échanges réseau

Uniquement entre votre ordinateur et Apple (iCloud), selon les conditions d'Apple. Le Bluetooth
relie l'ordinateur et l'iPhone sans passer par Internet. Trois autres accès réseau existent :

- les icônes des apps de l'iPhone qui envoient des notifications : Covalence demande l'icône
  d'une app au service public de recherche de l'App Store d'Apple, en n'envoyant que son
  identifiant (par exemple `net.whatsapp.WhatsApp`), jamais le contenu d'une notification.
  Les icônes sont gardées dans `~/.cache/covalence/app-icons/`. Pour désactiver, mettez
  `app-icons=false` dans le groupe `[notifications]` de `~/.config/covalence/covalenced.conf` ;
- les pochettes de ce que joue l'iPhone (Lecture en cours) : l'iPhone ne les envoie pas,
  Covalence interroge donc le service public de recherche iTunes d'Apple avec seulement
  l'artiste et le titre, et ne garde l'image que si les deux correspondent. Les pochettes sont
  gardées dans `~/.cache/covalence/artwork/`. Pour désactiver, mettez `artwork=false` dans le
  groupe `[media]` de `~/.config/covalence/covalenced.conf` ;
- le téléchargement de rclone, sur votre demande, depuis <https://downloads.rclone.org>.

## Suppression

1. Dans Covalence, désactivez les modules et déconnectez iCloud dans Services Apple.
2. Supprimez `~/.local/share/covalence/`, `~/.config/covalence/`, `~/.cache/covalence/` et `~/.cache/rclone/`.
3. Dans l'application Mots de passe et clés, supprimez les entrées « Covalence » et « iCloud ».

Désinstaller le paquet ne supprime pas ces fichiers.

Les messages et contacts de vos correspondants restent sous votre responsabilité : ne partagez pas
ces fichiers.
