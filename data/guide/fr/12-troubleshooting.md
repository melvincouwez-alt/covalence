title: Dépannage
icon: dialog-question
summary: Les problèmes courants et quoi essayer.
---
### « Le service Covalence ne répond pas »
Le service d'arrière-plan est arrêté. Ouvrez un Terminal et tapez `systemctl --user restart covalenced`. Son journal : `journalctl --user -u covalenced`.

### L'iPhone ne se reconnecte pas
1. Vérifiez que le Bluetooth est actif des deux côtés.
2. Cliquez sur **Reconnecter** dans l'[Aperçu](app:device).
3. Sinon, sur l'iPhone : Réglages › Bluetooth, touchez le nom de l'ordinateur.
4. En dernier recours, oubliez l'appareil des deux côtés et recommencez l'[appairage](guide:link).

### Pas de notifications
La liaison basse consommation n'est pas ouverte. Ouvrez nRF Connect sur l'iPhone et touchez **Connect** à côté de « Covalence ». Vérifiez aussi **Partager les notifications système**.

### Messages refusés par l'iPhone
Activez **Afficher les notifications** (Réglages › Bluetooth › ⓘ), puis cliquez sur **Vérifier** dans l'assistant.

### Un message apparaît en double
Supprimez la copie de trop (clic droit, **Supprimer de Covalence**). Si cela se reproduit, signalez-le sur la page du projet.

### Un message n'affiche que son début
C'est voulu tant qu'il n'est pas lu sur l'iPhone. Voir [Messages](guide:messages).

### Appel sans son
Pendant l'appel, activez **Audio PC**. Vérifiez la sortie et le micro dans Paramètres système › Son.

### Pas d'appels du tout
Si votre PipeWire est antérieur à la version 1.4, les appels ne sont pas disponibles. Voir [Téléphone](guide:phone).

### iCloud Drive ou Photos vide
Apple demande sans doute de reconfirmer la connexion : **Reconnecter…** dans [Services Apple](app:services). Journal : `journalctl --user -u covalence-icloud-drive`.

### « rclone introuvable » ou trop ancien
Il faut rclone 1.69 ou plus récent. Suivez la carte **Composants manquants** dans les [Réglages](app:settings).

### Les écouteurs restent sur « lecture de l'état »
Remettez les écouteurs dans le boîtier, refermez-le, puis rouvrez-le près de l'ordinateur.

### Signaler un problème
Ouvrez un ticket sur la page du projet (onglet Issues). Décrivez ce que vous faisiez, sans y copier vos messages ni vos numéros.
