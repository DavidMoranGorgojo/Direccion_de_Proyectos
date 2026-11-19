# Guía de instalación de Apptainer en Mac

**macOS + Lima + Linux**

Apptainer necesita Linux. En Mac, Lima prepara una máquina Linux. Esta guía instala Apptainer y abre el Frontend de ARSOFT en modo demo, sin arrancar Backend, base de datos ni Agentes.

## Antes de empezar

Necesitas un Mac Intel o Apple Silicon, conexión a Internet y permisos para instalar aplicaciones. Para ver la ventana del Frontend también necesitas XQuartz, que proporciona la pantalla gráfica X11 para Linux.

## 1. Instalar Lima y XQuartz

Abre **Terminal** en macOS. Si ya tienes Homebrew, instala ambos programas así:

```bash
brew install lima
brew install --cask xquartz
```

Si no tienes Homebrew, instálalo siguiendo su guía oficial: https://brew.sh

Cuando termine la instalación de XQuartz, cierra la sesión de macOS y vuelve a entrar si el sistema lo solicita. Después, abre XQuartz:

```bash
open -a XQuartz
```

## 2. Crear la máquina Linux

En Terminal de macOS, crea la máquina de Lima preparada para Apptainer:

```bash
limactl start --mount-writable template://apptainer
```

La primera vez se descargarán los componentes de Linux. Para mostrar aplicaciones gráficas, activa el reenvío X11 de Lima:

```bash
limactl edit apptainer
```

En el archivo YAML que se abre, añade esta sección al nivel principal. Si ya existe una sección `ssh`, añade solo la línea `forwardX11` dentro de ella:

```yaml
ssh:
  forwardX11: true
```

Guarda el archivo y cierra el editor. Reinicia la máquina:

```bash
limactl stop apptainer
limactl start apptainer
```

## 3. Preparar la pantalla gráfica y comprobar Apptainer

Entra en Linux:

```bash
limactl shell apptainer
```

Dentro de Linux, instala el pequeño componente que necesita el reenvío gráfico y comprueba Apptainer:

```bash
sudo apt update
sudo apt install -y xauth
apptainer --version
echo $DISPLAY
```

El último comando debe mostrar una dirección, por ejemplo `localhost:10.0`. Si no muestra nada, comprueba que XQuartz está abierto y que `forwardX11: true` quedó guardado; después vuelve a entrar con `limactl shell apptainer`.

## 4. Construir solo el Frontend

Guarda el repositorio dentro de tu carpeta personal de macOS para que Lima pueda verlo. Ya dentro de Linux, ve a la raíz del proyecto. Por ejemplo:

```bash
cd ~/proyectos/Direccion_de_Proyectos
```

Sustituye la ruta por la ubicación real. Construye únicamente el Frontend:

```bash
bash apptainer/build-all.sh frontend
```

La primera construcción puede tardar varios minutos. La imagen se guarda en `~/arsoft-images/frontend.sif`.

## 5. Abrir y comprobar la demo

En la misma sesión de Linux, arranca el Frontend en modo simulado:

```bash
unset ARSOFT_API_URL
bash apptainer/run-frontend.sh
```

Debe aparecer la ventana gráfica en macOS. El modo demo simula las respuestas localmente; no necesita API, Backend, base de datos, Agentes ni servicios externos. Esta guía comprueba que la aplicación abre correctamente.

Para cerrar la aplicación, cierra la ventana o pulsa `Ctrl+C` en la terminal de Linux. Para detener la máquina, desde Terminal de macOS ejecuta `limactl stop apptainer`.

## Enlaces oficiales

- Lima y Apptainer: https://apptainer.org/docs/admin/main/installation.html
- Lima: https://lima-vm.io/docs/
- XQuartz: https://www.xquartz.org/
