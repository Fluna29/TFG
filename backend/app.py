
from datetime import datetime, timedelta
from pymongo import MongoClient
from flask import Flask, request, jsonify
from bson.json_util import dumps
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from apscheduler.schedulers.background import BackgroundScheduler
import os
import atexit
from collections import Counter

app = Flask(__name__)

# MongoDB setup
client = MongoClient(os.environ.get("MONGO_CLIENT"))
db = client[os.environ.get("MONGO_DB")]
pedidos_collection = db[os.environ.get("MONGO_PEDIDOS_COLLECTION")]
contador_collection = db[os.environ.get("MONGO_CONTADOR_COLLECTION")]

# ID incremental
def generar_id_numerico():
    result = contador_collection.find_one_and_update(
        {"_id": "contador_pedidos"},
        {"$inc": {"valor": 1}},
        upsert=True,
        return_document=True
    )
    return result["valor"]

# Enviar mensaje de Whatsapp
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

# Validar hora apertura restaurante
def hora_valida(hora_str):
    try:
        hora = datetime.strptime(hora_str, "%H:%M").time()
        return (datetime.strptime("13:00", "%H:%M").time() <= hora <= datetime.strptime("16:00", "%H:%M").time()) or                (datetime.strptime("20:00", "%H:%M").time() <= hora <= datetime.strptime("23:00", "%H:%M").time())
    except ValueError:
        return False

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

# Recordatorios automáticos de hora de recogida del pedido
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
