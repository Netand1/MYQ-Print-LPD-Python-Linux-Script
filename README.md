# MYQ-Print-LPD-Python-Linux-Script

Client Python léger et autonome pour interroger l'état d'une file d'impression LPD (RFC 1179) et soumettre des travaux vers un serveur d'impression centralisé (notamment **MyQ** sous Windows).

Le script prend en charge la conversion automatique multi-formats (documents bureautiques, images, texte) et l'injection d'options d'impression via des commandes **PJL** (recto verso, mode couleur/mono).

---

## 💡 Fonctionnalités

- **Requêtes d'état (`lpq`)** :
  - Interrogation en mode court (`0x03`) ou détaillé (`0x04`).
  - Filtrage optionnel par nom d'utilisateur.
- **Conformité RFC 1179 (`--rfc-port`)** :
  - Support du liage (*bind*) sur la plage restreinte des ports source `721–731` (nécessite les privilèges `root`).
- **Envoi de travaux d'impression (`lpr`)** :
  - Envoi de fichiers bruts ou avec conversion à la volée.
  - Page de test intégrée (`--send-test`).
- **Chaîne de conversion automatique** :
  - Documents bureautiques (Office/OpenDocument/Text) $\rightarrow$ PDF via **LibreOffice** (en mode headless avec profil utilisateur isolé).
  - Images (JPEG, PNG, TIFF multipages, etc.) $\rightarrow$ PDF via **Pillow**.
  - PDF $\rightarrow$ PostScript ou PCL XL via **Ghostscript**.
- **Contrôle d'impression dynamique (PJL)** :
  - Injection d'en-têtes PJL pour forcer l'orientation/duplex (`off`, `long`, `short`) et le mode couleur (`mono`, `color`).

---

## 📦 Prérequis

### 1. Python
- Python 3.8 ou supérieur.
- Dépendance Python optionnelle (pour le traitement d'images) :
  ```bash
  pip install pillow
  ```

### 2. Utilitaires système (selon vos besoins de conversion)

Sur Debian/Ubuntu :
```bash
# Pour la conversion PDF -> PS / PCL
sudo apt install ghostscript

# Pour la conversion documents bureautiques -> PDF
sudo apt install libreoffice-writer libreoffice-calc

# Alternative Python Pillow via le gestionnaire de paquets
sudo apt install python3-pil
```

---

## 🚀 Installation

```bash
git clone https://github.com/votre-compte/MYQ-Print-LPD-Python-Linux-Script.git
cd MYQ-Print-LPD-Python-Linux-Script
chmod +x lpq_client.py
```

---

## 🛠️ Exemples d'utilisation

### 1. Interrogation de la file d'attente (`lpq`)

```bash
# Consultation simple (utilisateur par défaut : bob)
./lpq_client.py

# Consultation détaillée de la file d'attente pour tous les utilisateurs
./lpq_client.py --long --all-users

# Utilisation stricte des ports réservés RFC 721-731 (exigé par certains serveurs LPD durcis)
sudo ./lpq_client.py --rfc-port --host myq-server.domain.local --queue Follow_Me
```

### 2. Soumission de travaux d'impression (`lpr`)

```bash
# Envoyer une page de test texte
./lpq_client.py --send-test --user alice

# Envoyer un document Word (converti automatiquement en PDF avant envoi)
./lpq_client.py --send rapport.docx --user alice

# Envoyer une photo convertie en PostScript
./lpq_client.py --send photo.jpg --format ps

# Envoyer un PDF en forçant le Recto-Verso (bord long) et la Couleur Monochrome (Noir & Blanc)
./lpq_client.py --send document.pdf --duplex long --color mono --job-name "Rapport Mensuel"

# Envoyer un fichier brut sans aucune modification (mode raw)
./lpq_client.py --send étiquette.prn --raw
```

---

## 📖 Syntaxe et Options CLI

```text
Usage: lpq_client.py [-h] [--host HOST] [--port PORT] [--queue QUEUE] [--long]
                     [--user USER] [--all-users] [--rfc-port] [--timeout TIMEOUT]
                     [--send-test] [--send FICHIER] [--format {auto,pdf,ps,pcl}]
                     [--raw] [--duplex {off,long,short}] [--color {auto,mono,color}]
                     [--job-name JOB_NAME]
```

| Argument | Description | Valeur par défaut |
| :--- | :--- | :--- |
| `--host` | Adresse IP ou FQDN du serveur d'impression | `myq-01` |
| `--port` | Port TCP LPD | `515` |
| `--queue` | Nom de la file d'attente LPD | `Follow_Me` |
| `--long` | Activer l'affichage d'état détaillé (`0x04`) | `False` |
| `--user` | Nom d'utilisateur (répétable pour filtrer plusieurs utilisateurs) | `bob` |
| `--all-users` | Désactiver le filtrage par utilisateur | `False` |
| `--rfc-port` | Forcer l'utilisation des ports source RFC `721–731` | `False` |
| `--send-test` | Envoyer une page de test textuelle | `False` |
| `--send` | Chemin vers le fichier à imprimer | `None` |
| `--format` | Langage d'impression cible (`auto`, `pdf`, `ps`, `pcl`) | `auto` |
| `--raw` | Envoyer le fichier brut sans aucune conversion | `False` |
| `--duplex` | Option Recto/Verso (`off`, `long`, `short`) | `None` |
| `--color` | Mode couleur (`auto`, `mono`, `color`) | `auto` |
| `--job-name` | Nom du travail d'impression affiché dans la file | Nom du fichier |

---

## 💡 Conseils & Intégration

1. **Plage de ports RFC 1179 (`--rfc-port`)** :
   La norme RFC 1179 d'origine stipule que le client doit émettre depuis un port local compris entre `721` et `731`. Sur les systèmes Linux, l'accès aux ports $< 1024$ nécessite des privilèges d'administrateur (`root` ou `sudo`). Si votre serveur MyQ accepte les connexions LPD depuis n'importe quel port éphémère (comportement par défaut courant des serveurs Windows), vous n'avez pas besoin d'activer `--rfc-port`.

2. **Personnalisation de `parse_queue_listing`** :
   Le script contient un stub `TODO` dans la fonction `parse_queue_listing`. Selon la version et la configuration du serveur MyQ, le format de réponse brut d'une commande `lpq` peut varier. Pensez à capturer une réponse réelle de votre serveur MyQ pour y ajouter des expressions régulières (`re`) si vous souhaitez afficher un tableau formaté.

3. **Incompatibilité de profils LibreOffice** :
   La conversion via LibreOffice utilise l'argument `-env:UserInstallation` pointant vers un dossier temporaire. Cela garantit que la conversion headless ne bloquera pas si une instance utilisateur de LibreOffice est déjà ouverte en arrière-plan sur la machine Linux.