# Color Print Splitter 1.2.0

Complemento clásico para Blender 4.2 a 5.x (probado en 5.2.1 LTS). Sin dependencias externas.

## Regla de la casa: todo en modo Objeto

Todos los botones trabajan en modo Objeto y ninguno cambia de modo por su cuenta. Si estás en Edición, el panel lo avisa y tiene un botón para volver.

## Instalar

1. Desactiva la versión anterior en Editar > Preferencias > Complementos y reinicia Blender.
2. Instalar desde disco → `dist/color_print_splitter-1.2.0.zip` (sin descomprimir).
3. Vista 3D → tecla N → pestaña **Color Splitter**.

## Lo rápido: elegir y clic

- **Inserto de color**: elige forma y tamaño, selecciona el modelo, pulsa **«Clic en la zona para sacar inserto»** y pasa el ratón: el cortador se pega a la superficie (la mitad de su alto entra en la pieza). **Rueda** = tamaño. **Clic** = sale el inserto y queda su hueco.
- **Separar con espiga**: pulsa **«Clic para separar con espiga»**, **X / Y / Z** orientación, **rueda** inclina, **clic** corta.
- **Esc** cancela. Ctrl + rueda y botón central siguen moviendo la vista.

## Colocar a mano (desplegable «Colocar a mano / caras marcadas»)

**Separar con espiga**
1. Selecciona el modelo (modo Objeto) y pulsa «Añadir plano de corte». Colócalo (G / R).
2. Ajusta radio y longitud de la espiga y pulsa «Separar con espiga»: dos piezas con agujeros enfrentados y la espiga suelta al lado.

**Inserto de color** (ojo, botón, logo…)
1. Elige forma y tamaño del cortador y pulsa «Añadir cortador».
2. Colócalo sobre la zona y húndelo lo que quieras de profundidad (G / R / S). Lo que quede dentro del modelo es el inserto.
3. «Crear inserto y alojamiento»: sale el `_Inserto` (con el detalle de la superficie) y la `_Base` con su hueco agrandado por la holgura.

Cualquier malla cerrada sirve como cortador si le pones la propiedad personalizada `taller_role = cortador`. «Caras marcadas» sigue disponible para quien ya tenga una selección hecha.

Todas las medidas (imanes, espigas, holguras, tamaños) van en milímetros. «Unidades de entrada» se refiere a las coordenadas del modelo: «Escala de la escena» para escenas métricas normales; «1 unidad = 1 mm» para STL importados tal cual.

## Qué cambia respecto a 1.1

- Nada exige modo Edición: planos de corte y cortadores como objetos que mueves en modo Objeto.
- Las piezas vaciadas (cascos, bustos para espuma) se cortan bien: la tapa del corte queda en anillo y el hueco sigue hueco.
- Booleanas sin `bpy.ops` y con el solucionador «Manifold» de Blender 4.5+/5.x (mucho más rápido), con «Exacto» de respaldo.
- Exportación STL vectorizada: muy rápida con modelos de millones de caras.
- Si algo falla, se borra lo creado y el original sigue intacto; Ctrl+Z deshace una operación terminada.

## Límites

- El modelo debe ser una malla cerrada (manifold). Si no lo es, repáralo antes (por ejemplo en 3D LAB).
- La holgura de cortadores que no sean primitivas del complemento se aplica siguiendo las normales: es aproximada en esquinas.
- Imprime una muestra para ajustar holguras a tu impresora y material.
