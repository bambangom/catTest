from flask import Flask, render_template, request, send_file, send_from_directory, url_for
import openai, os, base64, pandas as pd, json, ast
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.debug = True

app.config["UPLOAD_FOLDER"] = "uploads"
app.config["RESULT_FOLDER"] = "results"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["RESULT_FOLDER"], exist_ok=True)

# ✅ Initialiser le client OpenAI
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyse_image_bytes(image_bytes):
    try:
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Tu es un expert en évaluation cadastrale au Sénégal. "
            "À partir d'une photo d'un bâtiment, tu dois : "
            "- Décrire brièvement l'apparence générale (style, matériaux, hauteur, état apparent). "
            "- Déterminer le nombre de niveaux selon : Terrain nu=0, RDC=1, R+1=2, R+2=3, etc. "
            "- Déterminer si l'immeuble est individuel, collectif ou terrain nu. "
            "- Catégoriser : 1/2/3/4 pour individuel ou A/B/C/D pour collectif, basé sur confort et équipements. "
            "- Calculer le coefficient d'entretien et vétusté (CENVET) entre 1.0 et 0.3 selon état. "
            "- Calculer le coefficient de voisinage (1.1, 1.0, 0.9 ou 0.8) selon avantages ou inconvénients. "
            "- Déterminer le coefficient d'abattement : "
            "1.0 si moins de 6 ans, "
            "entre 0.5 et 0.95 si plus vieux selon état apparent. "
            "Réponds uniquement en JSON : "
            "{'niveaux': ?, 'type_immeuble': 'individuel/collectif/terrain nu', "
            "'categorie': 'A/B/C/D/1/2/3/4/Aucun', "
            "'description': '...', "
            "'cenvet': ?, "
            "'coefficient_voisinage': ?, "
            "'coefficient_abatement': ?}"
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Voici l'image, analyse-la selon ces règles :"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}}
                    ],
                },
            ],
            temperature=0,
        )

        content = response.choices[0].message.content
        print("📥 Réponse OpenAI brute :")
        print(content)

        # ✅ Essayer de parser correctement le JSON
        try:
            json_part = content.split("{", 1)[1].rsplit("}", 1)[0]
            return json.loads("{" + json_part + "}")
        except Exception as e:
            print("⚠️ Échec parsing JSON :", e)
            return {"error": "Erreur de parsing OpenAI", "brute": content}

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
            if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue  # Ignorer fichiers non images

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
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/telecharger")
def telecharger():
    return send_file(os.path.join(app.config["RESULT_FOLDER"], "analyse.xlsx"), as_attachment=True)

# ✅ Important pour Render
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
