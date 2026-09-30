# Exportar el catálogo desde PrestaShop

El pipeline de este proyecto parte de dos exportaciones en CSV (separador `;`, codificación UTF-8).

## 1. Fichas (consulta SQL)

En el panel de administración: **Parámetros avanzados → Base de datos → Gestor SQL**. Crea una consulta nueva,
pega el SQL de abajo, ejecútala y descarga el resultado en CSV. Es la exportación que consume `fusionar_sql.py`
(ejemplo en `datos/crudo/export_sql_ejemplo.csv`).

```sql
SELECT p.id_product, p.reference, p.ean13, p.active,
       pl.name, pl.description_short, pl.description, pl.link_rewrite,
       m.name AS marca
FROM ps_product p
JOIN ps_product_lang pl
  ON pl.id_product = p.id_product AND pl.id_lang = 1 AND pl.id_shop = 1
LEFT JOIN ps_manufacturer m
  ON m.id_manufacturer = p.id_manufacturer;
```

### Cómo adaptarla

- **Prefijo de tablas.** `ps_` es el prefijo por defecto de PrestaShop. Si tu instalación usa otro, sustitúyelo en las
  tres tablas (`ps_product`, `ps_product_lang`, `ps_manufacturer`). Lo encuentras en el fichero de configuración de la
  tienda (`_DB_PREFIX_`) o mirando el nombre de las tablas en la base de datos.
- **Idioma (`id_lang`).** `1` suele ser el idioma por defecto, pero no siempre. Consulta tu identificador con
  `SELECT id_lang, name FROM ps_lang;` y cámbialo en la condición `pl.id_lang`.
- **Tienda (`id_shop`).** En instalaciones con una sola tienda es `1`. Si tienes varias, filtra por la que te interese.
- **Productos inactivos.** La consulta no filtra por `active`, así que incluye también los desactivados
  (`active = 0`). El pipeline se queda solo con los que aparecen en la exportación de productos del punto 2. Si quieres
  excluirlos ya en la consulta, añade `WHERE p.active = 1` al final.

## 2. Productos (exportación del catálogo)

En **Catálogo → Productos** exporta la lista en CSV. `convertir_json.py` espera estas columnas:
`Product ID`, `Imagen`, `Nombre`, `Referencia`, `Categoría`, `Precio (imp. excl.)`, `Precio (imp. incl.)`, `Cantidad`,
`Estado` y `Posición` (ejemplo en `datos/crudo/productos_ejemplo.csv`). La columna `Estado` se conserva tal cual
(`estado_raw`) pero no se interpreta.

## 3. Pipeline

```
convertir_json.py   productos.csv            -> datos/intermedio/catalogo_base.json
fusionar_sql.py     base + export SQL        -> datos/catalogo_ejemplo_crudo.json   (HTML y marcas sin limpiar)
limpiar_catalogo.py crudo                    -> datos/catalogo_ejemplo.json         (esquema que usa el buscador)
```

`generar_catalogo_ejemplo.py` ejecuta los tres pasos sobre un catálogo ficticio. Antes de publicar datos reales,
revisa que las fichas no contengan información que no quieras difundir.
