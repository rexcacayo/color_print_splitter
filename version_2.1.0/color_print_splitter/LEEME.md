# Color Print Splitter 2.1.0

Complemento clásico para Blender 4.2 a 5.x (probado en 5.2.1 LTS). Sin dependencias externas (usa numpy, que viene con Blender).

## Qué hace

Coge un modelo **pintado** (3MF pintado, OBJ con materiales, cualquier malla con un material por color) y lo separa en **una pieza por color**:

- El color mayoritario es la **base** (se puede cambiar con el botón de la casita).
- Cada zona de otro color sale como **pieza aparte** de 1,5 mm de grosor (menos donde el modelo es más fino). Su cara de fuera es la del modelo.
- En la base queda el **hueco con holgura** para encajar y pegar cada pieza.
- Las zonas demasiado estrechas (líneas finas) no se pueden imprimir aparte: se quedan en la base y el panel dice «pintar».

Pensado para imprimir sin AMS: cada color por separado y montar después.

## Uso

1. Selecciona el modelo → **Analizar colores**. Cierra la malla (los 3MF pintados vienen abiertos por las fronteras de color: uniones en T), limpia motas de color sueltas y mide cada zona.
2. Revisa la lista: cada color con su área, botón **Pieza** (sacarlo aparte o dejarlo para pintar) y la casita para elegir la base.
3. **Separar por colores**. Salen `<modelo>_base` y `<modelo>_<color>`. El original queda oculto.
4. **Exportar** (paso 3 del panel), en mm:
   - **Un 3MF** (recomendado): un solo archivo con todas las piezas, cada una con su nombre y su color. Se abre directo en Orca, Bambu o Prusa.
   - **Carpetas por color**: una carpeta por color y un STL por pieza, para imprimir por lotes de filamento (lo que hacía Auto Color Exporter, que queda retirado).
   - **STL sueltos**: un STL por pieza.

Ajustes: grosor de las piezas, holgura, ancho mínimo imprimible y tamaño de mota (los dos últimos requieren volver a analizar).

## Extra

«Inserto a mano»: para modelos de un solo color, clic sobre una zona (ojo, botón) con un cortador y sale como inserto con su hueco.

## Límites

- Un modelo de 2 millones de caras tarda 1–2 minutos (análisis + separación).
- Imprime una muestra para ajustar la holgura a tu impresora.
