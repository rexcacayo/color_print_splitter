# Color Print Splitter (MultiColor Kit)

> **Versión actual: 2.2.0** (Blender 4.2 – 5.x) → instalar `version_2.2.0/dist/color_print_splitter-2.2.0.zip`
>
> | Versión | Novedades |
> |---|---|
> | 2.2.0 | Lector propio de 3MF pintados (Bambu, Orca, Prusa): trae todos los colores del pincel y de cada pieza, que el importador de Blender perdía. Modelos que ya vienen en piezas por color: se separan y la base recibe sus huecos. |
> | 2.1.1 | Zonas finas pintadas por las dos caras (lazos, orejas): la base se abre limpia ahí y las piezas llegan a la mitad; sin paredes de grosor cero ni aristas no-manifold. |
> | 2.1.0 | Exportar en **un 3MF** con cada pieza nombrada y con su color, en **carpetas por color** (lo que hacía Auto Color Exporter) o en STL sueltos. |
> | 2.0.x | **Separar por colores**: lee un modelo pintado (3MF/OBJ), cose las uniones en T, limpia motas, alisa las fronteras y saca una pieza por color con su hueco y holgura en la base. Las zonas demasiado finas se marcan para pintar. |
> | 1.2.0 | Todo en modo Objeto, booleanas rápidas, piezas vaciadas. |
> | 1.1.0 | Primera versión empaquetada (espigas e insertos). |
>
> Cada carpeta `version_X` tiene el código y su ZIP en `dist/`. Detalle en el `LEEME.md` de cada versión.


Complemento para Blender que permite dividir un modelo en piezas para imprimirlas por separado en distintos colores y ensamblarlas mediante espigas o insertos, con adhesivo si es necesario.

Permite preparar modelos para impresión multicolor sin utilizar sistemas como AMS o MMU.

**Versión:** 1.1.0  
**Versión mínima declarada de Blender:** 4.2  
**Probado en:** Blender 5.2.1 LTS en Windows.

## Características principales

- **Separación con espiga:** separa una región seleccionada de la malla, cierra las superficies de separación y crea un alojamiento en ambas piezas.
- **Espiga independiente:** genera una espiga cilíndrica orientada horizontalmente para su posterior impresión.
- **Insertos superficiales:** convierte una selección de caras en una pieza con grosor y crea su alojamiento en el cuerpo principal. Puede utilizarse para detalles como insignias o zonas de una figura.
- **Medidas en milímetros:** permite ajustar el radio y la longitud de la espiga, la profundidad del inserto, la holgura y la pared mínima.
- **Conservación del original:** trabaja sobre copias y mantiene el objeto original oculto para poder recuperarlo.

## Instalación

1. Descarga `color_print_splitter-1.1.0.zip`. No lo descomprimas.
2. Abre Blender y ve a **Editar → Preferencias → Complementos**.
3. Abre el menú de la esquina superior derecha y selecciona **Instalar desde disco**.
4. Selecciona el archivo ZIP.
5. Activa el complemento si no se activa automáticamente.
6. En la vista 3D, pulsa **N** y abre la pestaña **Color Splitter**.

Si tienes instalada una versión anterior, desactívala y reinicia Blender antes de instalar la nueva versión.

## Uso básico

### Separar una pieza con espiga

1. Selecciona el objeto y entra en **Modo Edición** con la tecla **Tab**.
2. Activa la selección de caras y selecciona la región que quieres separar.
3. Comprueba que el borde entre la selección y el resto forme un único contorno plano.
4. En **Color Splitter**, configura las unidades, la holgura, la pared mínima y las dimensiones de la espiga.
5. Pulsa **Separar con espiga**.

El complemento creará dos piezas con sus alojamientos y una espiga independiente.

### Crear un inserto

1. En **Modo Edición**, selecciona las caras del detalle que quieres extraer.
2. Ajusta la profundidad del inserto, la holgura y la pared mínima.
3. Pulsa **Crear inserto y alojamiento**.

El complemento creará el inserto y su alojamiento en la base.

## Unidades y holguras

Las dimensiones de los encajes se introducen en milímetros. En **Unidades de entrada**, selecciona la opción que corresponda a la escala de tu modelo:

- **Escala de la escena:** utiliza las unidades configuradas en Blender.
- **1 unidad = 1 mm:** para modelos cuyas coordenadas representan directamente milímetros.

La holgura predeterminada es de **0,2 mm por radio**. Por ejemplo, una espiga de 4 mm de diámetro tendrá un alojamiento de 4,4 mm de diámetro.

En los insertos, la holgura se calcula mediante un desplazamiento aproximado de la superficie. El ajuste final depende de la impresora, el material y la geometría; conviene imprimir una muestra.

## Requisitos y limitaciones

- La separación parte de una sola malla cerrada.
- La región que se separa con espiga debe formar un volumen al cerrarse.
- El contorno de separación debe existir en la malla y ser plano: el complemento no permite dibujar un corte arbitrario.
- Aplica los modificadores activos sobre una copia antes de utilizar las operaciones.
- Las formas muy cóncavas, las autointersecciones o las paredes demasiado finas pueden impedir la operación.
- El complemento no detecta ni separa automáticamente las zonas por color. La selección de caras es manual.
- La asignación de colores y la exportación se realizan con otras herramientas, como **Auto Color Exporter**.

El objeto original queda oculto en la lista de objetos de Blender. Puedes volver a mostrarlo desde allí o deshacer una operación con **Ctrl + Z**.
## Licencia

GPL-3.0-or-later. Gratis para usar, modificar y compartir; si redistribuyes una versión modificada, publica también su código.
