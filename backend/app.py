from flask import Flask, request, jsonify
from pymongo import MongoClient
from bson.json_util import dumps
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from datetime import datetime
from datetime import time
import os
import re
from collections import Counter

app = Flask(__name__)

# Declaración de variables de entorno
client = MongoClient(os.environ.get("MONGO_CLIENT"))
db = client[os.environ.get("MONGO_DB")]
pedidos_collection = db[os.environ.get("MONGO_PEDIDOS_COLLECTION")]
contador_collection = db[os.environ.get("MONGO_CONTADOR_COLLECTION")]

# --- Funciones de validación ---

# Valida que el nombre introducido contenga solo letras y espacios
def es_nombre_valido(nombre):
    return bool(re.match(r"^[A-Za-zÁÉÍÓÚáéíóúÑñ\s]+$", nombre))


# Valida que la hora introducida esté en el formato HH:MM
def es_hora_valida(hora):
    return bool(re.match(r"^\d{2}:\d{2}$", hora))


# Valida que la fecha introducida esté en el formato DD-MM-AAAA
def es_fecha_valida(fecha):
    return bool(re.match(r"^\d{2}-\d{2}-\d{4}$", fecha))


#Valida que la hora introducida esté dentro del rango de apertura del restaurante
def hora_en_rango(hora):
    h = datetime.strptime(hora, "%H:%M").time()
    return (time(13, 0) <= h < time(16, 0)) or (time(20, 0) <= h < time(23, 0))


# Generar ID numérico incremental persistente usando base de datos en MongoDB colección "contador"
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


@app.route("/api/pedidos", methods=["GET"])
def obtener_pedidos():
    pedidos = list(pedidos_collection.find())
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
    if "_id" in datos:
        del datos["_id"]
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
        return app.response_class(
            response=dumps({"mensaje": "Pedido actualizado", "pedido": resultado}),
            status=200,
            mimetype="application/json"
        )
    return jsonify({"error": "Pedido no encontrado"}), 404


@app.route("/api/pedidos/<int:id_pedido>", methods=["DELETE"])
def eliminar_pedido(id_pedido):
    pedido = pedidos_collection.find_one({"id": id_pedido})
    if pedido:
        telefono = pedido.get("telefono")
        tipo = pedido.get("tipo")
        mensaje = "🛑 Tu reserva ha sido cancelada." if tipo == "reserva" else "🛑 Tu pedido ha sido cancelado."
        if telefono:
            enviar_mensaje_whatsapp(telefono, mensaje)
        pedidos_collection.delete_one({"id": id_pedido})
        return jsonify({"mensaje": "Pedido eliminado"}), 200
    return jsonify({"error": "Pedido no encontrado"}), 404


# Variables globales para el estado del usuario
estado_usuario = {}

# Lista de platos del menú
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

    if "hola" in mensaje or "buenos días" in mensaje or "buenas tardes" in mensaje or "buenas noches" in mensaje:
        msg.body("👋 ¡Hola! Ha contactado con la Trattoria Luna." +
                 "\nEstamos encantados de atenderle." +
                 "\nNuestro horario de apertura es: 13:00 a 16:00 y de 20:00 a 23:00" +
                 "\n\n¿Desea hacer una *reserva* o un *pedido para llevar*?")
        return str(respuesta)

    if "menu" in mensaje or "menú" in mensaje:
        msg.body("🇮🇹 Menú del Día – escriba *pedido* o *reserva* para comenzar:\n\n" + LISTADO_PRODUCTOS)
        return str(respuesta)

    # Inicializar el estado del usuario si no existe
    if "fase" not in usuario:
        usuario["fase"] = "esperando_tipo"

    # Esperando el tipo de reserva o pedido para llevar
    if usuario["fase"] == "esperando_tipo":
        if "reserva" in mensaje:
            usuario["tipo"] = "reserva"
        elif "llevar" in mensaje or "pedido" in mensaje:
            usuario["tipo"] = "pedido_para_llevar"
        else:
            msg.body("¿Desea hacer una *reserva* o un *pedido para llevar*?")
            return str(respuesta)
        usuario["fase"] = "esperando_nombre"
        msg.body("✏️ Por favor, escriba *solamente su nombre completo*, (Ej: Juan Pérez).")

    elif usuario["fase"] == "esperando_nombre":
        if not es_nombre_valido(mensaje):
            msg.body("❌ El nombre no debe contener números ni caracteres especiales. Ejemplo: Juan Pérez")
            return str(respuesta)
        usuario["nombre"] = mensaje.title()
        if usuario["tipo"] == "reserva":
            usuario["fase"] = "esperando_personas"
            msg.body("👥 ¿Para cuántas personas es la reserva?")
        else:
            usuario["fase"] = "esperando_hora"
            msg.body(
                "🕒 ¿A qué hora deseas recoger tu pedido? (Ej: 14:00) \n\nNuestro horario es de 13:00 a 16:00 y de 20:00 a 23:00")

    elif usuario["fase"] == "esperando_personas":
        try:
            usuario["personas"] = int(mensaje)
            usuario["fase"] = "esperando_fecha"
            msg.body("📅 ¿Para qué fecha deseas reservar? (Ej: 01-01-2025)")
        except ValueError:
            msg.body("❌ Por favor, escribe solo el número de personas. (Ej: 3)")


    elif usuario["fase"] == "esperando_fecha":
        if not es_fecha_valida(mensaje):
            msg.body("❌ La fecha debe tener el formato DD-MM-AAAA. Ejemplo: 01-01-2025")
            return str(respuesta)
        fecha_ingresada = datetime.strptime(mensaje, "%d-%m-%Y").date()
        if fecha_ingresada < datetime.now().date():
            msg.body("❌ La fecha no puede ser anterior a hoy. Por favor, ingresa una fecha válida.")
            return str(respuesta)
        usuario["fecha"] = mensaje
        usuario["fase"] = "esperando_hora"
        msg.body("🕒 ¿A qué hora deseas reservar mesa? (Ej: 14:00)")

    elif usuario["fase"] == "esperando_hora":
        if not es_hora_valida(mensaje):
            msg.body("❌ La hora debe tener el formato HH:MM. Ejemplo: 14:00")
            return str(respuesta)
        if usuario.get("fecha") == datetime.now().strftime("%d-%m-%Y"):
            hora_ingresada = datetime.strptime(mensaje, "%H:%M").time()
            if hora_ingresada <= datetime.now().time():
                msg.body("❌ La hora debe ser posterior a la actual.")
                return str(respuesta)
        if not hora_en_rango(mensaje):
            msg.body("❌ Solo aceptamos reservas/pedidos entre 13:00-16:00 y 20:00-23:00.")
            return str(respuesta)
        usuario["hora"] = mensaje

        #Si es una reserva, la guardamos ya en la base de datos ya que no requiere productos
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
                "📝 Escriba los *números* de los productos que desea, separados por comas.\n"
                "*Ej: 1, 2, 2, 5*\n\n" + LISTADO_PRODUCTOS
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
        msg.body("❓ No entendí tu mensaje. Por favor, escribe 'hola' para comenzar de nuevo.")
        del estado_usuario[from_numero]
    return str(respuesta)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
