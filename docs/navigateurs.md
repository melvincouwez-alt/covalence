# Codes SMS dans le navigateur (alpha)

Quand l'iPhone reçoit un SMS avec un code de vérification, Covalence le propose sous le champ de code du site ouvert dans le navigateur. Un clic sur la pastille « Code de Ma Banque : 482913 » remplit le champ. Le code n'entre dans la page qu'à ce clic.

Exception : un SMS qui lie le code à un site, sur sa dernière ligne (`@exemple.fr #482913`, le format que reconnaissent iOS et Android). Sur ce site, le code est rempli tout seul. Sur tout autre site, il n'est jamais proposé : une page d'hameçonnage qui déclenche l'envoi du code de votre banque ne le reçoit pas.

Cette fonction est en alpha. La notification avec « Copier le code » reste la voie stable.

## 1. Choisir le mode

Covalence › Réglages › Codes SMS : choisissez « Notification et navigateur (alpha) ».

## 2. Installer l'intégration

Toujours dans Réglages, cliquez sur « Installer l'intégration navigateur ». Covalence écrit le fichier `com.covalence.otp.json` pour chaque navigateur trouvé :

| Navigateur | Dossier |
|---|---|
| Google Chrome | `~/.config/google-chrome/NativeMessagingHosts/` |
| Chromium | `~/.config/chromium/NativeMessagingHosts/` |
| Microsoft Edge | `~/.config/microsoft-edge/NativeMessagingHosts/` |
| Firefox | `~/.mozilla/native-messaging-hosts/` |

Depuis un terminal : `covalenced --install-browser-host`.

## 3. Charger l'extension

L'extension est installée avec Covalence dans `~/.local/share/covalence/extension/` (ou `/usr/share/covalence/extension/` avec le paquet .deb). Le bouton en forme de dossier, dans Réglages, l'ouvre.

**Chrome, Chromium, Edge**

1. Ouvrez `chrome://extensions` (Edge : `edge://extensions`).
2. Activez le « Mode développeur ».
3. « Charger l'extension non empaquetée », puis choisissez le dossier `extension/chromium`.

L'identifiant affiché doit être `bbnmajflfndmkepfcnmpabhmneoplfkk`. C'est lui que l'intégration autorise.

**Firefox**

- Pour essayer : ouvrez `about:debugging#/runtime/this-firefox`, « Charger un module complémentaire temporaire », puis choisissez `extension/firefox/manifest.json`. Firefox l'oublie à sa fermeture.
- Pour la garder : Firefox Developer Edition ou Nightly acceptent le fichier non signé `extension/covalence-codes-firefox.xpi` après avoir mis `xpinstall.signatures.required` à `false` dans `about:config`. Firefox standard exige une extension signée par Mozilla (AMO) : prévu plus tard.
- Dans `about:addons` › Covalence › Permissions, autorisez l'accès à tous les sites, sinon la pastille n'apparaît pas.

## Fonctionnement et vie privée

- Le démon garde le dernier code en mémoire, jamais sur disque, et l'oublie après 3 minutes.
- La page ne voit pas la pastille (racine fantôme fermée). Le code entre dans la page seulement si vous cliquez, sauf pour un code lié à ce site par son SMS.
- Pages HTTPS de premier niveau seulement : ni `http://`, ni cadres intégrés d'un autre site.
- La pastille indique l'expéditeur du SMS : vérifiez qu'il correspond au site.
- L'extension ne demande le code que lorsqu'un champ de code a le focus : attribut `autocomplete="one-time-code"`, ou un nom qui y ressemble (otp, code, vérification…).
- Le code n'apparaît jamais dans le journal de Covalence.

## Limites connues

- **Identifiant de l'extension** : l'intégration n'accepte que l'identifiant de l'extension Covalence. Sous Chrome, cet identifiant découle de la clé publique du manifeste, qu'une autre extension installée à la main pourrait recopier ; sous Firefox, `otp@covalence.melvincouwez.github.io` n'est pas encore réservé sur addons.mozilla.org. N'installez pas d'extension d'origine inconnue.

- **Navigateurs Flatpak ou Snap** : ils lancent l'intégration dans leur bac à sable, sans accès au démon Covalence. Non pris en charge pour l'instant. Utilisez la notification « Copier le code ».
- Les champs découpés en une case par chiffre sont remplis case par case, mais certains sites les gèrent à leur façon.
- Un site qui nomme mal son champ n'aura pas de pastille. La copie depuis la notification marche partout.
