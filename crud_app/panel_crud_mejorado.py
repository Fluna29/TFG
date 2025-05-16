import sys
import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QInputDialog, QMessageBox, QDialog, QComboBox, QSpinBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from collections import Counter
from playsound import playsound
import numpy as np

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

class PanelPedidosCRUD(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Panel de Pedidos")
        self.setMinimumSize(900, 600)

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
        self.timer.start(10000)

    def init_pedidos(self):
        layout = QVBoxLayout(self.widget_pedidos)

        self.api_url = QLineEdit()
        self.api_url.setPlaceholderText("Introduce la URL de la API (Ej: https://tu-ngrok.io/api/pedidos)")
        self.api_url.setText("https://")
        layout.addWidget(self.api_url)

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
        url = self.api_url.text().strip()
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
                        QTimer.singleShot(3000, lambda txt=texto_clave: self.restaurar_color_por_texto(txt))

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

        nueva_hora, ok = QInputDialog.getText(self, "Editar hora", "Nueva hora (Ej: 14:00):", text=pedido.get("hora", ""))
        if not ok or not nueva_hora.strip():
            return

        nuevos_datos = {
            "nombre": nuevo_nombre.strip(),
            "hora": nueva_hora.strip()
        }

        url = self.api_url.text().strip().rstrip("/") + f"/{id_pedido}"
        try:
            response = requests.put(url, json=nuevos_datos)
            if response.status_code == 200:
                QMessageBox.information(self, "Éxito", "Pedido actualizado correctamente.")
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
            url = self.api_url.text().strip().rstrip("/") + f"/{id_pedido}"
            try:
                response = requests.put(url, json={"estado": nuevo_estado})
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

        url = self.api_url.text().strip().rstrip("/") + f"/{id_pedido}"
        try:
            response = requests.delete(url)
            if response.status_code == 200:
                self.cargar_pedidos()
            else:
                QMessageBox.critical(self, "Error", f"No se pudo eliminar: {response.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def mostrar_estadisticas(self):
        url = self.api_url.text().strip()
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

            franjas = ["11:00–13:00", "13:00–15:00", "15:00–17:00", "17:00–19:00", "19:00–21:00", "21:00–23:00"]
            reservas = dict.fromkeys(franjas, 0)
            pedidos_por_franja = dict.fromkeys(franjas, 0)

            for p in pedidos:
                hora = p.get("hora", "")[:5]
                tipo = p.get("tipo")
                try:
                    h = int(hora.split(":")[0])
                    if 11 <= h < 13:
                        clave = "11:00–13:00"
                    elif 13 <= h < 15:
                        clave = "13:00–15:00"
                    elif 15 <= h < 17:
                        clave = "15:00–17:00"
                    elif 17 <= h < 19:
                        clave = "17:00–19:00"
                    elif 19 <= h < 21:
                        clave = "19:00–21:00"
                    elif 21 <= h <= 23:
                        clave = "21:00–23:00"
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
        if not self.api_url.text().strip().startswith("http"):
            return
        self.cargar_pedidos()
        self.mostrar_estadisticas()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = PanelPedidosCRUD()
    ventana.show()
    sys.exit(app.exec())