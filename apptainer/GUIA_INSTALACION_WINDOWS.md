# Guía de instalación de Apptainer en Windows

**Windows + WSL 2 + Ubuntu**

Esta guía cubre la instalación del entorno y dos formas de ejecutar ARSOFT: la pila completa desde el repositorio y el Frontend aislado en modo demo.

## Antes de empezar

Necesitas Windows 11 o una versión reciente de Windows 10, conexión a Internet y permisos de administrador para instalar WSL. El Frontend gráfico se muestra mediante WSLg, incluido en Windows 11 y en versiones recientes de WSL.

## 1. Instalar Ubuntu con WSL 2

Abre **PowerShell como administrador** y ejecuta:

```powershell
wsl --install -d Ubuntu-24.04
```

Reinicia el equipo si Windows lo pide. Abre **Ubuntu** desde el menú Inicio y crea el usuario y la contraseña de Linux. Al escribir la contraseña no se muestran caracteres; es normal.

Comprueba que la distribución usa WSL 2, desde PowerShell:

```powershell
wsl -l -v
```

La columna `VERSION` debe indicar `2`.

## 2. Instalar Apptainer

En la terminal de Ubuntu, ejecuta:

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:apptainer/ppa
sudo apt update
sudo apt install -y apptainer
apptainer version
```

Si aparece un número de versión, Apptainer está instalado.

## 3. Instalar y arrancar la pila completa

Abre Ubuntu y ve a la raíz del repositorio, es decir, la carpeta que contiene `apptainer/`. Si el repositorio está en una unidad de Windows, aparecerá bajo `/mnt/c`; adapta y entrecomilla la ruta si contiene espacios:

```bash
cd "/mnt/c/Users/tu-usuario/ruta/al/repositorio"
```

Construye y arranca toda la aplicación con este comando:

```bash
bash apptainer/start-all.sh
```

En el primer uso, el comando crea la configuración local, construye las imágenes SIF que falten y levanta PostgreSQL con pgvector, Backend y Agentes. La construcción descarga dependencias, puede pedir la contraseña Linux para `sudo` y necesita varios GB libres. Después verifica el login, el historial y la conexión del Frontend con el Backend, y abre la ventana gráfica.

Para la prueba básica, inicia sesión con `usuario1` y contraseña `usuario123`. Son credenciales de desarrollo local; no las uses en producción.

Si no hay PDF en `data/manuales`, la ingesta se omite y la aplicación continúa con la prueba básica. Para probar respuestas de Agentes, Ollama y el modelo configurado deben estar disponibles; para probar el RAG también hacen falta los documentos. Cierra la ventana o pulsa `Ctrl+C` en la terminal para detener las instancias iniciadas por este comando. La base de datos, las imágenes y las cachés se conservan para el siguiente arranque.

Para más opciones de configuración, consulta [README.md](README.md).

## 4. Construir solo el Frontend (modo demo)

Este flujo es opcional y solo comprueba la interfaz gráfica. Desde la raíz del repositorio, ejecuta:

```bash
bash apptainer/build-all.sh frontend
```

La primera construcción puede tardar varios minutos.

## 5. Abrir y comprobar la demo

En la misma terminal de Ubuntu, fuerza el modo simulado y arranca la interfaz:

```bash
unset ARSOFT_API_URL
bash apptainer/run-frontend.sh
```

Debe aparecer la ventana gráfica del Frontend. El modo demo simula las respuestas localmente; no necesita API, Backend, base de datos, Agentes ni servicios externos.

Para cerrarla, cierra la ventana o vuelve a la terminal y pulsa `Ctrl+C`.

## Si no aparece la ventana

Comprueba que Windows tiene WSL actualizado. En PowerShell ejecuta `wsl --update`, reinicia Ubuntu y vuelve a lanzar el paso 5. El comando `echo $DISPLAY` dentro de Ubuntu debe mostrar una dirección.

## Enlaces oficiales

- WSL: https://learn.microsoft.com/windows/wsl/install
- Instalación de Apptainer: https://apptainer.org/docs/admin/main/installation.html
