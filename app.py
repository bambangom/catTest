from flask import Flask, render_template, request, send_file, send_from_directory, url_for, abort, jsonify
import openai, os, base64, pandas as pd, json
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from textwrap import wrap

app = Flask(__name__)
app.debug = True

app.config["UPLOAD_FOLDER"] = "uploads"
app.config["RESULT_FOLDER"] = "results"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["RESULT_FOLDER"], exist_ok=True)

# Initialiser OpenAI
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyse_image_bytes(image_bytes):
    try:
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Tu es un expert en évaluation cadastrale au Sénégal, spécialisé dans l’analyse visuelle automatisée des bâtiments. "
            "À partir d'une photo, tu dois :\n"
            "- Décrire brièvement l'apparence (matériaux, style, état de la façade, hauteur).\n"
            "- Déterminer le nombre de niveaux visibles : Terrain nu=0, RDC=1, R+1=2, etc.\n"
            "- Vérifier la présence de compteurs visibles ou boîtes électriques : plusieurs compteurs = collectif.\n"
            "- Évaluer individuel/collectif selon l'apparence.\n"
            "- Catégoriser : 1/2/3/4 (individuel) ou A/B/C/D (collectif).\n"
            "- Attention : ne jamais classer en 1 ou A un bâtiment dégradé.\n"
            "- Calculer :\n"
            "  ▪ CENVET (1.0 à 0.3)\n"
            "  ▪ Coefficient voisinage (1.1, 1.0, 0.9, 0.8)\n"
            "  ▪ Coefficient abattement (1.0 si <6 ans, sinon 0.5-0.95).\n"
            "Réponds en JSON :\n"
            "{'niveaux': ?, 'type_immeuble': 'individuel/collectif/terrain nu', 'categorie': 'A/B/C/D/1/2/3/4/Aucun', 'description': '...', 'cenvet': ?, 'coefficient_voisinage': ?, 'coefficient_abatement': ?}"
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "Voici l'image, analyse-la."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}}
                ]}
            ],
            temperature=0,
        )

        content = response.choices[0].message.content
        print("📅 Réponse OpenAI brute :")
        print(content)

        try:
            json_part = content.split("{", 1)[1].rsplit("}", 1)[0]
            return json.loads("{" + json_part + "}")
        except Exception as e:
            print("⚠️ Erreur parsing JSON :", e)
            return {"error": "Erreur parsing OpenAI", "brute": content}
    except Exception as e:
        print(f"❌ Erreur OpenAI : {e}")
        return {"error": str(e)}

@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    if request.method == "POST":
        files = request.files.getlist("images")
        if not files or files[0].filename == "":
            return render_template("index.html", resultats=[], message="⚠️ Veuillez sélectionner une image.")

        for file in files:
            if not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                continue

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            with open(filepath, "rb") as f:
                image_bytes = f.read()

            data = analyse_image_bytes(image_bytes)

            results.append({
                "image_url": url_for('uploaded_file', filename=filename),
                "NICAD": filename.rsplit(".", 1)[0],
                "Type d'immeuble": data.get("type_immeuble", data.get("error", "Erreur")),
                "Catégorie": data.get("categorie", "Non précisé"),
                "Niveaux": data.get("niveaux", "Non précisé"),
                "Description": data.get("description", "Non précisé"),
                "CENVET": data.get("cenvet", "Non précisé"),
                "Voisinage": data.get("coefficient_voisinage", "Non précisé"),
                "Abattement": data.get("coefficient_abatement", "Non précisé")
            })

        df = pd.DataFrame(results)
        df.to_excel(os.path.join(app.config["RESULT_FOLDER"], "analyse.xlsx"), index=False)

    return render_template("index.html", resultats=results)

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/telecharger")
def telecharger():
    return send_file(os.path.join(app.config["RESULT_FOLDER"], "analyse.xlsx"), as_attachment=True)

@app.route("/pdf/<nicad>")
def generate_pdf(nicad):
    result_file = os.path.join(app.config["RESULT_FOLDER"], "analyse.xlsx")
    df = pd.read_excel(result_file)

    df["NICAD_CLEAN"] = df["NICAD"].astype(str).str.split(".").str[0]
    match = df[df["NICAD_CLEAN"] == nicad]

    if not match.empty:
        row = match.iloc[0]
    else:
        return "NICAD non trouvé", 404

    pdf_path = os.path.join(app.config["RESULT_FOLDER"], f"{nicad}.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "■ Rapport d’Analyse Cadastrale par IA")
    y -= 40

    champs = {
        "NICAD": row.get("NICAD", ""),
        "Type": row.get("Type d'immeuble", ""),
        "Catégorie": row.get("Catégorie", ""),
        "Niveaux": row.get("Niveaux", ""),
        "Description": row.get("Description", ""),
        "CENVET": row.get("CENVET", ""),
        "Voisinage": row.get("Voisinage", ""),
        "Abattement": row.get("Abattement", "")
    }

    c.setFont("Helvetica", 12)
    for label, value in champs.items():
        if label == "Description":
            c.drawString(50, y, f"{label} :")
            y -= 18
            phrases = [p.strip() for p in value.replace("\n", " ").split(".") if p.strip()]
            for phrase in phrases:
                for line in wrap(f"- {phrase.strip()}.", width=90):
                    c.drawString(70, y, line)
                    y -= 15
        else:
            c.drawString(50, y, f"{label} : {value}")
            y -= 22

    for ext in [".jpg", ".jpeg", ".png"]:
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], nicad + ext)
        if os.path.exists(image_path):
            try:
                c.drawImage(ImageReader(image_path), 50, y - 200, width=200, height=150)
                break
            except Exception as e:
                print(f"Erreur image PDF : {e}")

    c.save()
    return send_file(pdf_path, as_attachment=True)

@app.route("/api/analyse", methods=["POST"])
def api_analyse():
    if "image" not in request.files:
        return jsonify({"error": "Aucune image fournie"}), 400
    image = request.files["image"]
    image_bytes = image.read()
    result = analyse_image_bytes(image_bytes)
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
