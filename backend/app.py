# backend/app.py

from flask import Flask, request, jsonify
from pymongo import MongoClient
from bson.json_util import dumps
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from datetime import datetime, timedelta
from collections import Counter
from apscheduler.schedulers.background import BackgroundScheduler
import os
import atexit

app = Flask(__name__)

# Conexión a MongoDB Atlas
client = MongoClient(os.environ.get("MONGO_CLIENT"))
db = client[os.environ.get("MONGO_DB")]
pedidos_collection = db[os.environ.get("MONGO_PEDIDOS_COLLECTION")]
contador_collection = db[os.environ.get("MONGO_CONTADOR_COLLECTION")]

# Generar ID numérico incremental persistente
def generar_id_numerico():
    result = contador_collection.find_one_and_update(
        {"_id": "contador_pedidos"},
        {"$inc": {"valor": 1}},
        upsert=True,
        return_document=True
    )
    return result["valor"]

def enviar_mensaje_whatsapp(telefono, mensaje):
    try:
        account_sid = os.environ.get("TWILIO_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            from_="whatsapp:+14155238886",
            to=f"whatsapp:{telefono}",
            body=mensaje
        )
        print("Mensaje enviado:", msg.sid)
    except Exception as e:
        print("Error al enviar mensaje:", e)

# --- API CRUD ---

@app.route("/api/pedidos", methods=["GET"])
def obtener_pedidos():
    query = {}
    fecha_str = request.args.get("fecha")
    tipo = request.args.get("tipo")
    if fecha_str:
        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            query["fecha"] = fecha
        except ValueError:
            pass
    if tipo:
        query["tipo"] = tipo
    pedidos = list(pedidos_collection.find(query))
    return dumps(pedidos), 200

@app.route("/api/pedidos", methods=["POST"])
def crear_pedido():
    data = request.get_json()
    data["id"] = generar_id_numerico()
    data["timestamp"] = datetime.now().isoformat()
    pedidos_collection.insert_one(data)
    return jsonify({"mensaje": "Pedido creado", "pedido": data}), 201

@app.route("/api/pedidos/<int:id_pedido>", methods=["PUT"])
def actualizar_pedido(id_pedido):
    datos = request.get_json()
    datos["timestamp"] = datetime.now().isoformat()
    resultado = pedidos_collection.find_one_and_update(
        {"id": id_pedido},
        {"$set": datos},
        return_document=True
    )
    if resultado:
        # Enviar mensaje si se actualizó el estado
        if "estado" in datos and "telefono" in resultado:
            nombre = resultado.get("nombre", "")
            mensaje = {
                "pendiente": f"🕒 Hola {nombre}, tu pedido ha sido recibido. ¡Estamos preparando todo para ti!\n\n– Trattoria Luna 🍝",
                "en_preparacion": f"👨‍🍳 {nombre}, estamos cocinando tu pedido. ¡Ya casi está listo!\n\n– Trattoria Luna 🍝",
                "preparado": f"✅ ¡{nombre}, tu pedido ya está listo para recoger! 🍽️\n\n– Trattoria Luna 🍝",
                "entregado": f"🚚 Pedido entregado, {nombre}. ¡Gracias por elegirnos! 😄\n\n– Trattoria Luna 🍝"
            }.get(datos["estado"], None)
            if mensaje:
                enviar_mensaje_whatsapp(resultado["telefono"], mensaje)
        return jsonify({"mensaje": "Pedido actualizado", "pedido": resultado})
    return jsonify({"error": "Pedido no encontrado"}), 404

@app.route("/api/pedidos/<int:id_pedido>", methods=["DELETE"])
def eliminar_pedido(id_pedido):
    pedido = pedidos_collection.find_one({"id": id_pedido})
    if pedido:
        telefono = pedido.get("telefono")
        tipo = pedido.get("tipo")
        mensaje = "🛑 Tu reserva ha sido cancelada." if tipo == "reserva" else "🛑 Tu pedido ha sido cancelado."
        if telefono:
            enviar_mensaje_whatsapp(telefono, mensaje + "\n\n– Trattoria Luna 🍝")
        pedidos_collection.delete_one({"id": id_pedido})
        return jsonify({"mensaje": "Pedido eliminado"}), 200
    return jsonify({"error": "Pedido no encontrado"}), 404

# --- WhatsApp Bot ---

estado_usuario = {}

PLATOS = {
    "1": "Spaghetti alla Carbonara",
    "2": "Pasta al Pomodoro",
    "3": "Fettuccine Alfredo",
    "4": "Penne al Pesto con Pollo",
    "5": "Pizza Margherita",
    "6": "Pizza Prosciutto e Funghi",
    "7": "Lasagna Tradicional",
    "8": "Risotto ai Frutti di Mare",
    "9": "Ensalada Caprese",
    "10": "Saltimbocca alla Romana"
}
LISTADO_PRODUCTOS = "\n".join([f"{n}. {nombre}" for n, nombre in PLATOS.items()])

@app.route('/bot', methods=['POST'])
def bot():
    from_numero = request.form.get("From", "").replace("whatsapp:", "")
    mensaje = request.form.get("Body", "").strip().lower()
    respuesta = MessagingResponse()
    msg = respuesta.message()

    if from_numero not in estado_usuario:
        estado_usuario[from_numero] = {"fase": "esperando_tipo"}

    usuario = estado_usuario[from_numero]

    if "menu" in mensaje or "menú" in mensaje:
        msg.body("🇮🇹 Menú del Día – escribe *pedido* o *reserva* para comenzar:\n\n" + LISTADO_PRODUCTOS)
        return str(respuesta)

    if usuario["fase"] == "esperando_tipo":
        if "reserva" in mensaje:
            usuario["tipo"] = "reserva"
        elif "llevar" in mensaje or "pedido" in mensaje:
            usuario["tipo"] = "pedido_para_llevar"
        else:
            msg.body("¿Deseas hacer una *reserva* o un *pedido para llevar*?")
            return str(respuesta)
        usuario["fase"] = "esperando_nombre"
        msg.body("✏️ Por favor, escribe *solo tu nombre completo*, sin frases adicionales.")

    elif usuario["fase"] == "esperando_nombre":
        usuario["nombre"] = mensaje.title()
        if usuario["tipo"] == "reserva":
            usuario["fase"] = "esperando_personas"
            msg.body("👥 ¿Para cuántas personas es la reserva?")
        else:
            usuario["fase"] = "esperando_hora"
            msg.body("🕒 ¿A qué hora deseas recoger tu pedido? (Ej: 14:00)")

    elif usuario["fase"] == "esperando_personas":
        try:
            usuario["personas"] = int(mensaje)
            usuario["fase"] = "esperando_fecha"
            msg.body("📅 ¿Para qué fecha deseas reservar? (Ej: 2025-05-14)")
        except ValueError:
            msg.body("❌ Por favor, escribe solo el número de personas. (Ej: 3)")

    elif usuario["fase"] == "esperando_fecha":
        usuario["fecha"] = mensaje
        usuario["fase"] = "esperando_hora"
        msg.body("🕒 ¿A qué hora deseas reservar mesa? (Ej: 14:00)")

    elif usuario["fase"] == "esperando_hora":
        usuario["hora"] = mensaje
        if usuario["tipo"] == "reserva":
            payload = {
                "id": generar_id_numerico(),
                "telefono": from_numero,
                "tipo": usuario["tipo"],
                "nombre": usuario["nombre"],
                "fecha": usuario["fecha"],
                "personas": usuario["personas"],
                "hora": usuario["hora"],
                "productos": [],
                "timestamp": datetime.now().isoformat()
            }
            pedidos_collection.insert_one(payload)
            msg.body(
                f"✅ ¡Reserva confirmada!\n\n"
                f"📌 Nombre: {usuario['nombre']}\n"
                f"📅 Fecha: {usuario['fecha']}\n"
                f"👥 Personas: {usuario['personas']}\n"
                f"🕒 Hora: {usuario['hora']}"
            )
            del estado_usuario[from_numero]
        else:
            usuario["fase"] = "esperando_productos"
            msg.body(
                "📝 Escribe los *números* de los productos que deseas, separados por comas.\n"
                "Ej: 1, 2, 2, 5\n\n" + LISTADO_PRODUCTOS
            )

    elif usuario["fase"] == "esperando_productos":
        numeros = [n.strip() for n in mensaje.split(",")]
        cantidades = Counter(numeros)
        productos = [f"{PLATOS.get(n)} (x{cant})" for n, cant in cantidades.items() if PLATOS.get(n)]
        usuario["productos"] = productos
        payload = {
            "id": generar_id_numerico(),
            "telefono": from_numero,
            "tipo": usuario["tipo"],
            "nombre": usuario["nombre"],
            "hora": usuario["hora"],
            "productos": usuario["productos"],
            "timestamp": datetime.now().isoformat(),
            "estado": "pendiente"
        }
        pedidos_collection.insert_one(payload)
        msg.body(
            f"✅ ¡Pedido para llevar confirmado!\n\n"
            f"📌 Nombre: {usuario['nombre']}\n"
            f"🕒 Hora de recogida: {usuario['hora']}\n"
            f"🍽️ Productos:\n- " + "\n- ".join(usuario["productos"])
        )
        del estado_usuario[from_numero]

    else:
        msg.body("👋 ¡Hola! ¿Deseas hacer una *reserva* o un *pedido para llevar*?")

    return str(respuesta)

# --- Recordatorios automáticos ---

def enviar_recordatorios_pedidos():
    ahora = datetime.now()
    en_20_min = ahora + timedelta(minutes=20)
    pedidos = pedidos_collection.find({
        "tipo": "pedido_para_llevar",
        "estado": "pendiente",
        "fecha": en_20_min.date()
    })

    for pedido in pedidos:
        try:
            hora_pedido = datetime.strptime(pedido["hora"], "%H:%M").time()
            fecha_hora = datetime.combine(pedido["fecha"], hora_pedido)
            minutos_restantes = (fecha_hora - ahora).total_seconds() / 60
            if 19 <= minutos_restantes <= 21:
                nombre = pedido.get("nombre", "cliente")
                productos = pedido.get("productos", [])
                productos_texto = "\n- " + "\n- ".join(productos) if productos else ""
                enviar_mensaje_whatsapp(
                    pedido.get("telefono"),
                    f"🔔 Hola {nombre}, tu pedido estará listo para recoger a las {pedido['hora']}.\n"
                    f"🍽️ Productos:\n{productos_texto}\n\n– Trattoria Luna 🍝"
                )
        except Exception as e:
            print("Error en recordatorio:", e)

scheduler = BackgroundScheduler()
scheduler.add_job(enviar_recordatorios_pedidos, 'interval', minutes=1)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)