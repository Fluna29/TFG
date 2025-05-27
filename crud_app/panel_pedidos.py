import sys
from datetime import datetime, time

import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QInputDialog, QMessageBox, QDialog, QComboBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from collections import Counter
from playsound import playsound
import numpy as np

#Diccionario con los platos disponibles
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


class EstadoDialog(QDialog):
    def __init__(self, estado_actual=None):
        super().__init__()
        self.setWindowTitle("Cambiar estado del pedido")
        self.setMinimumSize(300, 100)
        layout = QVBoxLayout(self)
        self.combo = QComboBox()
        self.combo.addItems(["pendiente", "en_preparacion", "preparado", "entregado"])
        if estado_actual:
            index = self.combo.findText(estado_actual)
            if index != -1:
                self.combo.setCurrentIndex(index)
        layout.addWidget(self.combo)
        self.boton_ok = QPushButton("Guardar")
        self.boton_ok.clicked.connect(self.accept)
        layout.addWidget(self.boton_ok)

    def obtener_estado(self):
        return self.combo.currentText()

class DialogoEditarProductos(QDialog):
    def __init__(self, productos_existentes=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar productos del pedido")
        self.setMinimumSize(450, 300)
        self.productos = {}

        layout = QVBoxLayout(self)

        self.lista_productos = QListWidget()
        layout.addWidget(self.lista_productos)

        botones_layout = QHBoxLayout()

        # Combo para seleccionar producto
        self.combo_producto = QComboBox()
        self.combo_producto.addItems(PLATOS.values())

        # Campo para cantidad
        self.input_cantidad = QLineEdit()
        self.input_cantidad.setPlaceholderText("Cantidad")

        # Botón añadir
        self.boton_anadir = QPushButton("Añadir")
        self.boton_anadir.clicked.connect(self.anadir_producto)

        botones_layout.addWidget(self.combo_producto)
        botones_layout.addWidget(self.input_cantidad)
        botones_layout.addWidget(self.boton_anadir)
        layout.addLayout(botones_layout)

        self.boton_guardar = QPushButton("Guardar y cerrar")
        self.boton_guardar.clicked.connect(self.accept)
        layout.addWidget(self.boton_guardar)

        # Cargar productos existentes si hay
        if productos_existentes:
            for prod in productos_existentes:
                if " (x" in prod:
                    nombre = prod.split(" (x")[0]
                    cantidad = int(prod.split(" (x")[1].replace(")", ""))
                else:
                    nombre = prod
                    cantidad = 1
                self.productos[nombre] = cantidad
            self.actualizar_lista()

    def actualizar_lista(self):
        self.lista_productos.clear()
        for nombre, cantidad in self.productos.items():
            item = QListWidgetItem(f"{nombre} (x{cantidad})")
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            label = QPushButton(f"{nombre} (x{cantidad})")
            label.setEnabled(False)
            btn_sumar = QPushButton("+")
            btn_restar = QPushButton("-")
            btn_sumar.clicked.connect(lambda _, n=nombre: self.modificar_cantidad(n, 1))
            btn_restar.clicked.connect(lambda _, n=nombre: self.modificar_cantidad(n, -1))
            layout.addWidget(label)
            layout.addWidget(btn_sumar)
            layout.addWidget(btn_restar)
            item.setSizeHint(widget.sizeHint())
            self.lista_productos.addItem(item)
            self.lista_productos.setItemWidget(item, widget)

    def modificar_cantidad(self, nombre, cambio):
        if nombre in self.productos:
            self.productos[nombre] += cambio
            if self.productos[nombre] <= 0:
                del self.productos[nombre]
        self.actualizar_lista()

    def anadir_producto(self):
        nombre = self.combo_producto.currentText()
        try:
            cantidad = int(self.input_cantidad.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Error", "Cantidad inválida")
            return

        if not nombre or cantidad <= 0:
            QMessageBox.warning(self, "Error", "Nombre y cantidad deben ser válidos.")
            return

        self.productos[nombre] = self.productos.get(nombre, 0) + cantidad
        self.input_cantidad.clear()
        self.actualizar_lista()

    def obtener_productos(self):
        return [f"{n} (x{c})" for n, c in self.productos.items()]


class PanelPedidosCRUD(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Panel de Pedidos")
        self.setMinimumSize(900, 600)

        # Introducimos aquí la URL de la API donde están almacenados nuestros pedidos.
        self.api_url = "https://chatbot-tfg-backend.onrender.com/api/pedidos"
        if not self.api_url:
            QMessageBox.critical(self, "Error", "No se ha definido la variable de entorno API_PEDIDOS_URL.")
            sys.exit(1)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.widget_pedidos = QWidget()
        self.widget_estadisticas = QWidget()
        self.tabs.addTab(self.widget_pedidos, "📋 Pedidos")
        self.tabs.addTab(self.widget_estadisticas, "📊 Estadísticas")

        self.init_pedidos()
        self.init_estadisticas()

        self.ids_anteriores = set()
        self.resaltados = {}
        self.lista_pedidos.itemSelectionChanged.connect(self.quitar_resaltado_seleccionado)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.actualizar_automatica)
        self.timer.start(6500)

    def init_pedidos(self):
        layout = QVBoxLayout(self.widget_pedidos)

        self.lista_pedidos = QListWidget()
        layout.addWidget(self.lista_pedidos)

        botones = QHBoxLayout()
        self.boton_cargar = QPushButton("🔄 Cargar")
        self.boton_editar = QPushButton("✏️ Editar seleccionado")
        self.boton_estado = QPushButton("🔁 Cambiar estado")
        self.boton_borrar = QPushButton("🗑️ Eliminar seleccionado")

        self.boton_cargar.clicked.connect(self.cargar_pedidos)
        self.boton_editar.clicked.connect(self.editar_pedido)
        self.boton_estado.clicked.connect(self.cambiar_estado_pedido)
        self.boton_borrar.clicked.connect(self.eliminar_pedido)

        botones.addWidget(self.boton_cargar)
        botones.addWidget(self.boton_editar)
        botones.addWidget(self.boton_estado)
        botones.addWidget(self.boton_borrar)
        layout.addLayout(botones)

    def init_estadisticas(self):
        layout = QVBoxLayout(self.widget_estadisticas)
        self.canvas = FigureCanvas(Figure(figsize=(10, 4)))
        layout.addWidget(self.canvas)
        self.ax, self.ax2, self.ax3 = self.canvas.figure.subplots(1, 3)

        self.boton_actualizar = QPushButton("🔁 Actualizar estadísticas")
        self.boton_actualizar.clicked.connect(self.mostrar_estadisticas)
        layout.addWidget(self.boton_actualizar)

    def quitar_resaltado_seleccionado(self):
        item = self.lista_pedidos.currentItem()
        if item and item.background() == QColor("#DDE6ED"):
            item.setBackground(Qt.white)

    def cargar_pedidos(self):
        self.lista_pedidos.clear()
        url = self.api_url
        if not url:
            return
        try:
            response = requests.get(url)
            if response.status_code == 200:
                nuevos_ids = set()
                self.pedidos_actuales = response.json()
                for pedido in self.pedidos_actuales:
                    nuevos_ids.add(str(pedido.get("id")))
                    tipo = pedido.get("tipo", "").replace("_", " ").title()
                    nombre = pedido.get("nombre", "")
                    hora = pedido.get("hora", "")
                    telefono = pedido.get("telefono", "")

                    item_text = (
                        f"ID {pedido.get('id')}\n"
                        f"📌 {tipo} | {nombre} | {hora}\n"
                        f"📱 {telefono}\n"
                    )

                    if pedido.get("tipo") == "reserva":
                        fecha = pedido.get("fecha")
                        if fecha:
                            item_text += f"📅 Fecha: {fecha}\n"
                        personas = pedido.get("personas")
                        if personas:
                            item_text += f"👥 Personas: {personas}\n"

                    productos = pedido.get("productos", [])
                    if productos:
                        item_text += "🍽️ Productos:\n"
                        for producto in productos:
                            item_text += f"   - {producto}\n"

                    if pedido.get("tipo") == "pedido_para_llevar":
                        estado = pedido.get("estado", "")
                        if estado:
                            item_text += f"📦 Estado: {estado}\n"

                    item = QListWidgetItem(item_text)

                    if str(pedido.get("id")) not in self.ids_anteriores:
                        item.setBackground(QColor("#DDE6ED"))
                        texto_clave = item.text()
                        self.resaltados[texto_clave] = item
                        playsound("Notificacion.wav", block=False)
                        QTimer.singleShot(1500, lambda txt=texto_clave: self.restaurar_color_por_texto(txt))

                    self.lista_pedidos.addItem(item)

                self.ids_anteriores = nuevos_ids
        except Exception as e:
            print("Error:", e)

    def restaurar_color_por_texto(self, texto):
        item = self.resaltados.get(texto)
        if item:
            item.setBackground(Qt.white)

    def editar_pedido(self):
        item = self.lista_pedidos.currentItem()
        if not item:
            QMessageBox.warning(self, "Atención", "Selecciona un pedido primero.")
            return

        texto = item.text()
        id_linea = texto.split("\n")[0]
        try:
            id_pedido = int(id_linea.replace("ID ", "").strip())
        except:
            QMessageBox.critical(self, "Error", "No se pudo obtener el ID del pedido.")
            return

        pedido = next((p for p in self.pedidos_actuales if p.get("id") == id_pedido), None)
        if not pedido:
            QMessageBox.critical(self, "Error", "Pedido no encontrado.")
            return

        nuevo_nombre, ok = QInputDialog.getText(self, "Editar nombre", "Nuevo nombre:", text=pedido.get("nombre", ""))
        if not ok or not nuevo_nombre.strip():
            return

        if len(nuevo_nombre.strip().split()) < 2 or any(char.isdigit() for char in nuevo_nombre):
            QMessageBox.warning(self, "Nombre inválido", "Introduce al menos nombre y apellido, sin números.")
            return

        # Ediciones especiales si es reserva
        nueva_fecha = pedido.get("fecha", "")
        nuevas_personas = pedido.get("personas", 1)

        if pedido.get("tipo") == "reserva":
            nueva_fecha, ok = QInputDialog.getText(self, "Editar fecha", "Nueva fecha (DD-MM-YYYY):", text=nueva_fecha)
            if not ok or not nueva_fecha.strip():
                return
            try:
                datetime.strptime(nueva_fecha.strip(), "%d-%m-%Y")  # validación
            except ValueError:
                QMessageBox.warning(self, "Formato incorrecto", "La fecha debe estar en formato DD-MM-YYYY.")
                return

            personas_texto, ok = QInputDialog.getText(self, "Editar personas", "¿Cuántas personas?",
                                                    text=str(nuevas_personas))
            if not ok or not personas_texto.strip().isdigit():
                return

            nuevas_personas = int(personas_texto.strip())
            if nuevas_personas < 1 or nuevas_personas > 40:
                QMessageBox.warning(self, "Número inválido", "Introduce entre 1 y 40 personas.")
                return

        nueva_hora, ok = QInputDialog.getText(self, "Editar hora", "Nueva hora (Ej: 14:00):",
                                              text=pedido.get("hora", ""))
        if not ok or not nueva_hora.strip():
            return

        try:
            hora_obj = datetime.strptime(nueva_hora.strip(), "%H:%M").time()
            if not ((time(13, 0) <= hora_obj < time(16, 0)) or (time(20, 0) <= hora_obj < time(23, 0))):
                QMessageBox.warning(self, "Hora inválida", "Introduce una hora entre 13:00–16:00 o 20:00–23:00.")
                return
        except ValueError:
            QMessageBox.warning(self, "Formato incorrecto", "La hora debe estar en formato HH:MM.")
            return

        nuevos_datos = pedido.copy()
        nuevos_datos["nombre"] = nuevo_nombre.strip()
        nuevos_datos["hora"] = nueva_hora.strip()

        if pedido.get("tipo") == "reserva":
            nuevos_datos["fecha"] = nueva_fecha.strip()
            nuevos_datos["personas"] = nuevas_personas

        elif pedido.get("tipo") == "pedido_para_llevar":
            productos_actuales = nuevos_datos.get("productos", [])
            dlg = DialogoEditarProductos(productos_existentes=productos_actuales, parent=self)
            if dlg.exec():
                nuevos_datos["productos"] = dlg.obtener_productos()

        if "_id" in nuevos_datos:
            del nuevos_datos["_id"]

        url = self.api_url.rstrip("/") + f"/{id_pedido}"
        try:
            response = requests.put(url, json=nuevos_datos)
            if response.status_code == 200:
                # Comparar cambios y mostrar resumen
                cambios = []
                if pedido.get("nombre") != nuevos_datos.get("nombre"):
                    cambios.append(f"- Nombre: de '{pedido.get('nombre')}' a '{nuevos_datos.get('nombre')}'")
                if pedido.get("hora") != nuevos_datos.get("hora"):
                    cambios.append(f"- Hora: de '{pedido.get('hora')}' a '{nuevos_datos.get('hora')}'")
                if pedido.get("tipo") == "reserva":
                    if pedido.get("fecha") != nuevos_datos.get("fecha"):
                        cambios.append(f"- Fecha: de '{pedido.get('fecha')}' a '{nuevos_datos.get('fecha')}'")
                    if pedido.get("personas") != nuevos_datos.get("personas"):
                        cambios.append(f"- Personas: de {pedido.get('personas')} a {nuevos_datos.get('personas')}")
                if pedido.get("tipo") == "pedido_para_llevar" and pedido.get("productos") != nuevos_datos.get(
                        "productos"):
                    cambios.append("- Productos: modificados")

                if cambios:
                    mensaje = "✏️ El pedido fue actualizado:\n" + "\n".join(cambios)
                else:
                    mensaje = "✅ Pedido actualizado, sin cambios visibles."

                QMessageBox.information(self, "Pedido actualizado", mensaje)
                self.cargar_pedidos()
            else:
                QMessageBox.critical(self, "Error", f"No se pudo actualizar: {response.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error de conexión", str(e))

    def cambiar_estado_pedido(self):
        item = self.lista_pedidos.currentItem()
        if not item:
            QMessageBox.warning(self, "Atención", "Selecciona un pedido primero.")
            return

        texto = item.text()
        id_linea = texto.split("\n")[0]
        try:
            id_pedido = int(id_linea.replace("ID ", "").strip())
        except:
            QMessageBox.critical(self, "Error", "No se pudo obtener el ID del pedido.")
            return

        pedido = next((p for p in self.pedidos_actuales if p.get("id") == id_pedido), None)
        if not pedido or pedido.get("tipo") != "pedido_para_llevar":
            QMessageBox.warning(self, "Atención", "Solo se puede cambiar el estado de pedidos para llevar.")
            return

        dlg = EstadoDialog(estado_actual=pedido.get("estado"))
        if dlg.exec():
            nuevo_estado = dlg.obtener_estado()
            nuevos_datos = pedido.copy()
            nuevos_datos["estado"] = nuevo_estado
            url = self.api_url + f"/{id_pedido}"
            try:
                response = requests.put(url, json=nuevos_datos)
                if response.status_code == 200:
                    QMessageBox.information(self, "Éxito", "Estado actualizado correctamente.")
                    self.cargar_pedidos()
                else:
                    QMessageBox.critical(self, "Error", f"No se pudo actualizar estado: {response.text}")
            except Exception as e:
                QMessageBox.critical(self, "Error de conexión", str(e))

    def eliminar_pedido(self):
        item = self.lista_pedidos.currentItem()
        if not item:
            return
        confirmar = QMessageBox.question(self, "Confirmar eliminación", "¿Seguro que quieres eliminar este pedido?", QMessageBox.Yes | QMessageBox.No)
        if confirmar != QMessageBox.Yes:
            return

        texto = item.text()
        id_linea = texto.split("\n")[0]
        try:
            id_pedido = int(id_linea.replace("ID ", "").strip())
        except:
            QMessageBox.critical(self, "Error", "No se pudo obtener el ID del pedido.")
            return

        url = self.api_url.strip().rstrip("/") + f"/{id_pedido}"
        try:
            response = requests.delete(url)
            if response.status_code == 200:
                self.cargar_pedidos()
            else:
                QMessageBox.critical(self, "Error", f"No se pudo eliminar: {response.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def mostrar_estadisticas(self):
        url = self.api_url
        if not url:
            QMessageBox.warning(self, "Error", "Introduce la URL de la API.")
            return
        try:
            response = requests.get(url)
            if response.status_code != 200:
                raise Exception("Error de respuesta")

            pedidos = response.json()
            tipos = Counter(p["tipo"] for p in pedidos)
            productos = Counter()
            for p in pedidos:
                for prod in p.get("productos", []):
                    nombre = prod.split(" (x")[0]
                    cantidad = int(prod.split(" (x")[1].replace(")", ""))
                    productos[nombre] += cantidad

            self.ax.clear()
            self.ax2.clear()
            self.ax3.clear()

            self.ax.bar(tipos.keys(), tipos.values(), color=["skyblue", "lightgreen"])
            self.ax.set_title("Reservas vs Pedidos")
            self.ax.set_ylabel("Cantidad")

            if productos:
                nombres = list(productos.keys())
                cantidades = list(productos.values())
                self.ax2.barh(nombres, cantidades, color="salmon")
                self.ax2.set_title("Productos más vendidos")
                self.ax2.set_xlabel("Unidades")

            franjas = ["13:00–16:00", "20:00–23:00"]
            reservas = dict.fromkeys(franjas, 0)
            pedidos_por_franja = dict.fromkeys(franjas, 0)

            for p in pedidos:
                hora = p.get("hora", "")[:5]
                tipo = p.get("tipo")
                try:
                    h = int(hora.split(":")[0])
                    if 13 <= h < 16:
                        clave = "13:00–16:00"
                    elif 20 <= h < 23:
                        clave = "20:00–23:00"
                    else:
                        continue

                    if tipo == "reserva":
                        reservas[clave] += 1
                    elif tipo == "pedido_para_llevar":
                        pedidos_por_franja[clave] += 1
                except:
                    pass

            x = np.arange(len(franjas))
            self.ax3.bar(x, list(reservas.values()), width=0.4, label="Reservas", color="steelblue")
            self.ax3.bar(x, list(pedidos_por_franja.values()), bottom=list(reservas.values()), width=0.4,
                        label="Pedidos", color="mediumseagreen")
            self.ax3.set_xticks(x)
            self.ax3.set_xticklabels(franjas, rotation=45)
            self.ax3.set_title("Reservas vs Pedidos por Franja Horaria")
            self.ax3.set_ylabel("Cantidad")
            self.ax3.legend()

            self.canvas.draw()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo cargar estadísticas: {e}")

    def actualizar_automatica(self):
        if not self.api_url:
            return
        self.cargar_pedidos()
        self.mostrar_estadisticas()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = PanelPedidosCRUD()
    ventana.show()
    sys.exit(app.exec())