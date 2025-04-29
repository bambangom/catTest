from flask import Flask, render_template, request, send_file, send_from_directory, url_for, abort
import openai, os, base64, pandas as pd, json, ast
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
        print("📅 Réponse OpenAI brute :")
        print(content)

        try:
            json_part = content.split("{", 1)[1].rsplit("}", 1)[0]
            return json.loads("{" + json_part + "}")
        except Exception as e:
            print("⚠️ Échec parsing JSON :", e)
            return {"error": "Erreur de parsing OpenAI", "brute": content}

    except Exception as e:
        print(f"❌ Erreur OpenAI : {e}")
        return {"error": str(e)}

@app.route("/pdf/<nicad>")
def generate_pdf(nicad):
    result_file = os.path.join(app.config["RESULT_FOLDER"], "analyse.xlsx")
    df = pd.read_excel(result_file)
    df["NICAD_CLEAN"] = df["NICAD"].astype(str).str.split(".").str[0]
    match = df[df["NICAD_CLEAN"] == nicad]

    if match.empty or match.iloc[0].isnull().any():
        image_path = None
        for ext in [".jpg", ".jpeg", ".png"]:
            path = os.path.join(app.config["UPLOAD_FOLDER"], nicad + ext)
            if os.path.exists(path):
                image_path = path
                break

        if image_path:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            data_ai = analyse_image_bytes(image_bytes)

            new_row = {
                "NICAD": nicad,
                "Type d'immeuble": data_ai.get("type_immeuble", "Non précisé"),
                "Catégorie": data_ai.get("categorie", "Non précisé),
                "Niveaux": data_ai.get("niveaux", "Non précisé"),
                "Description": data_ai.get("description", "Non précisé"),
                "CENVET": data_ai.get("cenvet", "-"),
                "Voisinage": data_ai.get("coefficient_voisinage", "-"),
                "Abattement": data_ai.get("coefficient_abatement", "-")
            }

            df = df[df["NICAD_CLEAN"] != nicad]
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            df.to_excel(result_file, index=False)
            row = new_row
        else:
            row = {
                "NICAD": nicad,
                "Type d'immeuble": "Non trouvé",
                "Catégorie": "Non précisé",
                "Niveaux": "Non précisé",
                "Description": "Aperçu image uniquement. Analyse non retrouvée.",
                "CENVET": "-",
                "Voisinage": "-",
                "Abattement": "-"
            }
    else:
        row = match.iloc[0]

    pdf_path = os.path.join(app.config["RESULT_FOLDER"], f"{nicad}.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "\u25a0 Rapport d’Analyse Cadastrale par IA")
    y -= 40

    champs = {
        "NICAD": row.get("NICAD", nicad),
        "Type": row.get("Type d'immeuble", "Non précisé"),
        "Catégorie": row.get("Catégorie", "Non précisé"),
        "Niveaux": row.get("Niveaux", "Non précisé"),
        "Description": row.get("Description", "Non précisé"),
        "CENVET": row.get("CENVET", "-"),
        "Voisinage": row.get("Voisinage", "-"),
        "Abattement": row.get("Abattement", "-")
    }

    c.setFont("Helvetica", 12)
    for label, value in champs.items():
        if label == "Description" and isinstance(value, str):
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
