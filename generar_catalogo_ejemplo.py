#!/usr/bin/env python3
"""Genera un catálogo FICTICIO de unos 100 productos para probar el asistente (semilla fija: siempre sale lo mismo).

Escribe, en datos/:
  crudo/productos_ejemplo.csv      exportación de productos al estilo de PrestaShop (precios, stock, nombres con ruido)
  crudo/export_sql_ejemplo.csv     exportación SQL con las fichas en HTML, la marca (con mayúsculas inconsistentes) y EAN
  catalogo_ejemplo_crudo.json      el resultado de convertir y fusionar ambos ficheros, sin limpiar
  catalogo_ejemplo.json            el catálogo limpio, con el esquema que usa el buscador
y, en la raíz, evaluacion.json con consultas y los ids esperados.

Incluye a propósito casos difíciles: fichas sin descripción, descripciones que solo repiten el nombre, texto basura,
variantes por tamaño, SPF, edad, tono o graduación, productos sin stock, stock negativo, marcas con mayúsculas
inconsistentes, marca propia y fichas largas con secciones de modo de empleo y precauciones.

Todos los nombres, marcas y textos son inventados. Los EAN empiezan por 200 (rango de uso interno: no son códigos reales).

Uso:  .venv312/bin/python generar_catalogo_ejemplo.py [--semilla 42]
"""
import argparse
import csv
import json
import random
import re
import unicodedata

import config
import convertir_json
import fusionar_sql
import limpiar_catalogo

DATOS = config.BASE / "datos"
CRUDO = DATOS / "crudo"
IVA = 1.21
PRIMER_ID = 101
MARCA_PROPIA = "Marca Ejemplo"

# ----------------------------------------------------------------------------------------------------------------
# Familias de producto: (clave, categoría, marca, nombre base, descripción corta, frases, modo de empleo, precauciones,
#                        variantes[(sufijo, precio con IVA, stock, etiquetas)], opciones)
# Las variantes de una familia comparten la descripción (distinto tamaño, SPF, edad, tono o graduación).
# ----------------------------------------------------------------------------------------------------------------
FAMILIAS = [
    ("sol_fluido", "Protección solar", "Solenza", "Solenza Fluido Facial Solar",
     "Protector solar facial de textura fluida y acabado mate",
     ["Protector solar facial de textura fluida y acabado mate, pensado para el uso diario.",
      "Protege frente a la radiación UVA y UVB y se absorbe rápidamente sin dejar residuo blanco.",
      "Su fórmula sin perfume es adecuada para pieles normales y mixtas.",
      "Puede usarse como base antes del maquillaje."],
     "Aplicar sobre el rostro limpio 15 minutos antes de la exposición solar. Reaplicar cada dos horas y después del baño.",
     ["Uso externo.", "Evitar el contacto con los ojos.", "No sustituye a la sombra ni a la ropa protectora."],
     [("SPF 30 50 ml", 17.95, 14, ("sol", "sol_facial")), ("SPF 50 50 ml", 19.95, 9, ("sol", "sol_facial"))], {}),
    ("sol_corporal", "Protección solar", "Solenza", "Solenza Leche Solar Corporal",
     "Leche solar corporal de rápida absorción y resistente al agua",
     ["Leche solar corporal de rápida absorción, con textura ligera que no deja sensación grasa.",
      "Es resistente al agua y ofrece una protección amplia frente a la radiación UVA y UVB.",
      "Se extiende con facilidad sobre piel húmeda o seca.",
      "El envase grande está pensado para toda la familia."],
     "Aplicar de forma generosa y uniforme sobre la piel seca 20 minutos antes de salir al sol. Reaplicar cada dos horas.",
     ["Uso externo.", "No aplicar sobre heridas.", "Guardar en un lugar que los niños pequeños no puedan alcanzar."],
     [("SPF 30 200 ml", 15.50, 20, ("sol",)), ("SPF 50 200 ml", 16.90, 18, ("sol",)), ("SPF 50 400 ml", 26.50, 6, ("sol",))], {}),
    ("sol_ninos", "Protección solar", "Solenza", "Solenza Spray Solar Pediátrico",
     "Spray solar de alta protección para la piel de los niños",
     ["Spray solar de alta protección formulado para la piel delicada de los niños.",
      "Su textura ligera se aplica en cualquier posición y se absorbe sin frotar.",
      "Resiste el agua y el sudor durante el juego al aire libre.",
      "No contiene perfume."],
     "Agitar antes de usar. Aplicar de forma abundante sobre la piel seca 15 minutos antes de la exposición y reaplicar cada dos horas.",
     ["Uso externo.", "No pulverizar directamente sobre la cara: aplicar con la mano.", "Evitar el contacto con los ojos."],
     [("Niños SPF 50 200 ml", 18.50, 11, ("sol", "sol_ninos")), ("Bebés SPF 50 200 ml", 19.90, 8, ("sol", "sol_ninos"))], {}),
    ("sol_ninos_loc", "Protección solar", "Kiddora", "Kiddora Loción Solar Niños",
     "Loción solar infantil de muy alta protección",
     ["Loción solar infantil de muy alta protección con textura cremosa y sin perfume.",
      "Protege frente a la radiación UVA y UVB y resiste el agua.",
      "Indicada para pieles sensibles de niños a partir de tres años.",
      "El formato de 250 ml permite cubrir cuerpo y cara durante varios días."],
     "Aplicar sobre la piel seca media hora antes de la exposición. Reaplicar cada dos horas y después de cada baño.",
     ["Uso externo.", "Evitar la exposición directa en las horas centrales del día.", "Interrumpir el uso si aparece irritación."],
     [("SPF 50+ 250 ml", 17.95, 10, ("sol", "sol_ninos"))], {}),
    ("sol_stick", "Protección solar", "Solenza", "Solenza Stick Labial Solar", "Protector labial con filtro solar",
     ["Protector labial con filtro solar y manteca nutritiva.", "Se desliza con suavidad y deja los labios cómodos."],
     "", [], [("SPF 30 4 g", 4.90, 0, ("sol",))], {"ligero": True}),
    ("sol_propia", "Protección solar", MARCA_PROPIA, "Marca Ejemplo Protector Solar Facial",
     "Protector solar facial para cada día",
     ["Protector solar facial de uso diario con textura ligera y acabado natural.",
      "Ofrece alta protección frente a la radiación UVA y UVB.",
      "Apto para todo tipo de pieles, sin perfume.",
      "Se absorbe rápido y no deja película blanca."],
     "Aplicar sobre el rostro limpio cada mañana y reaplicar cada dos horas si se está al aire libre.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("SPF 50 50 ml", 12.90, 25, ("sol", "sol_facial", "marca_propia"))], {}),
    ("aftersun", "Protección solar", "Solenza", "Solenza Gel Aftersun",
     "Gel refrescante para después de la exposición solar",
     ["Gel refrescante para aplicar después de la exposición solar.", "Su textura acuosa se absorbe al instante y deja la piel cómoda.",
      "Contiene extracto de aloe y glicerina.", "Sin alcohol."],
     "Aplicar sobre la piel limpia y seca tras el baño o la ducha, tantas veces como se desee.",
     ["Uso externo.", "No aplicar sobre heridas abiertas."],
     [("200 ml", 9.50, -2, ("sol",))], {}),
    ("panal", "Cuidado del bebé", "Kiddora", "Kiddora Crema Cambio de Pañal",
     "Crema protectora para la zona del pañal",
     ["Crema protectora para la zona del pañal con óxido de zinc y pantenol.", "Forma una barrera que aísla la piel de la humedad.",
      "Su textura untuosa se extiende con facilidad.", "Sin perfume ni colorantes."],
     "En cada cambio de pañal, limpiar y secar la zona y aplicar una capa fina de crema.",
     ["Uso externo.", "Evitar el contacto con los ojos.", "Consultar al pediatra si la irritación persiste."],
     [("100 ml", 6.95, 17, ("panal",)), ("200 ml", 10.90, 12, ("panal",))], {}),
    ("bebe_gel", "Cuidado del bebé", "Kiddora", "Kiddora Gel de Baño y Champú",
     "Gel suave para el baño del bebé, de la cabeza a los pies",
     ["Gel suave para el baño del bebé, de la cabeza a los pies.", "Limpia sin irritar y no pica en los ojos.",
      "Su fórmula sin jabón respeta la piel delicada.", "Con dosificador."],
     "Aplicar una pequeña cantidad sobre la piel húmeda, masajear suavemente y aclarar con abundante agua.",
     ["Uso externo.", "Guardar en un sitio al que los niños no tengan acceso."],
     [("500 ml", 8.50, 15, ("bebe",))], {}),
    ("bebe_colonia", "Cuidado del bebé", "Kiddora", "Kiddora Colonia Suave", "Colonia suave para bebés",
     ["Colonia suave para bebés con aroma fresco y delicado.", "Sin alcohol añadido y de bajo contenido en perfume."],
     "", [], [("200 ml", 7.20, 9, ("bebe",))], {"ligero": True}),
    ("toallitas", "Cuidado del bebé", "Kiddora", "Kiddora Toallitas Húmedas", "Toallitas húmedas suaves para la piel del bebé",
     ["Toallitas húmedas suaves para la limpieza diaria de la piel del bebé.", "Impregnadas con una loción sin alcohol ni perfume.",
      "Resistentes y fáciles de sacar del envase con una mano.", "Envase con tapa adhesiva que conserva la humedad."],
     "Extraer una toallita, limpiar la zona y desechar. No tirar por el inodoro.",
     ["Uso externo.", "No reutilizar."],
     [("72 unidades", 2.95, 40, ("bebe",)), ("3 x 72 unidades", 7.95, 22, ("bebe",))], {}),
    ("chupete", "Cuidado del bebé", "Kiddora", "Kiddora Chupete de Silicona", "Chupete de silicona con tetina anatómica",
     ["Chupete de silicona con tetina anatómica y escudo ventilado.", "Fabricado sin bisfenol A.",
      "Se entrega en estuche esterilizable.", "Disponible en tres tamaños según la edad."],
     "Esterilizar antes del primer uso y revisar con regularidad.",
     ["Comprobar el estado de la tetina antes de cada uso.", "No sujetar con cintas ni cuerdas.", "Sustituir al primer signo de deterioro."],
     [("0-6 meses", 4.90, 13, ("bebe",)), ("6-18 meses", 4.90, 0, ("bebe",)), ("Más de 18 meses", 4.90, 7, ("bebe",))], {}),
    ("atopica_crema", "Cuidado del bebé", "Pielara", "Pielara Crema Emoliente Atópica", "Crema emoliente para pieles muy secas o atópicas",
     ["Crema emoliente para el cuidado diario de pieles muy secas o con tendencia atópica.", "Repone los lípidos de la piel y alivia la sensación de tirantez.",
      "Su textura rica se absorbe sin dejar sensación pegajosa.", "Sin perfume, apta para bebés y adultos."],
     "Aplicar una o dos veces al día sobre la piel limpia y seca, con un suave masaje.",
     ["Uso externo.", "No aplicar sobre lesiones abiertas.", "Consultar al pediatra o al farmacéutico ante lesiones persistentes."],
     [("400 ml", 21.50, 10, ("atopica",)), ("100 ml", 9.90, 16, ("atopica",))], {}),
    ("atopica_gel", "Cuidado del bebé", "Pielara", "Pielara Gel de Baño Atópico", "Gel de baño sin jabón para pieles atópicas",
     ["Gel de baño sin jabón para pieles secas y atópicas.", "Limpia con suavidad y respeta la barrera cutánea.",
      "Sin perfume ni colorantes.", "Apto desde el nacimiento."],
     "Verter en el agua del baño o aplicar sobre la piel húmeda y aclarar.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("500 ml", 13.90, 8, ("atopica",))], {}),
    ("atopica_bebe", "Cuidado del bebé", "Kiddora", "Kiddora Crema Hidratante Bebé Piel Atópica", "Crema hidratante para bebés con piel atópica",
     ["Crema hidratante para el cuidado de la piel atópica del bebé.", "Calma el picor asociado a la sequedad y refuerza la barrera de la piel.",
      "Textura untuosa de rápida absorción.", "Sin perfume ni conservantes agresivos."],
     "Aplicar una o dos veces al día después del baño, con la piel todavía ligeramente húmeda.",
     ["Uso externo.", "Consultar al pediatra si aparecen lesiones."],
     [("250 ml", 15.90, 11, ("atopica", "bebe"))], {}),
    ("boca_spray", "Higiene bucal", "Oralys", "Oralys Spray Boca Seca", "Spray humectante para aliviar la sensación de boca seca",
     ["Spray humectante que alivia la sensación de boca seca y la incomodidad al hablar.", "Forma una película que mantiene la mucosa hidratada.",
      "Formato de bolsillo para llevar siempre encima.", "Sabor suave a menta."],
     "Pulverizar dos o tres veces sobre la lengua y las mejillas las veces que sea necesario.",
     ["No ingerir.", "Guardar en un sitio al que los niños no tengan acceso."],
     [("15 ml", 7.95, 19, ("boca_seca",))], {}),
    ("boca_gel", "Higiene bucal", "Oralys", "Oralys Gel Humectante Boca Seca", "Gel humectante de larga duración para la boca seca",
     ["Gel humectante de larga duración para la sequedad bucal.", "Su textura viscosa tapiza la mucosa y prolonga la hidratación durante la noche.",
      "Sin alcohol ni azúcares añadidos.", "Tubo de 50 ml con aplicador."],
     "Aplicar una pequeña cantidad sobre la yema del dedo y extender por encías, mejillas y lengua, sobre todo antes de acostarse.",
     ["Uso bucal.", "No ingerir de forma intencionada."],
     [("50 ml", 15.50, 9, ("boca_seca",))], {}),
    ("boca_colutorio", "Higiene bucal", "Oralys", "Oralys Colutorio Boca Seca", "Colutorio sin alcohol para la sequedad bucal",
     ["Colutorio sin alcohol formulado para la sequedad bucal.", "Hidrata la mucosa y refresca el aliento sin irritar.",
      "Uso diario, también después del cepillado.", "Envase de 500 ml."],
     "Enjuagar con 10 ml durante 30 segundos, sin diluir, y escupir. No aclarar con agua.",
     ["No ingerir.", "No recomendado para menores de seis años sin supervisión."],
     [("500 ml", 12.95, 13, ("boca_seca",))], {}),
    ("pasta", "Higiene bucal", "Oralys", "Oralys Pasta Dentífrica Encías", "Pasta dentífrica para el cuidado diario de las encías",
     ["Pasta dentífrica para el cuidado diario de las encías.", "Con flúor, contribuye a fortalecer el esmalte.", "Sabor a menta suave."],
     "", [], [("75 ml", 5.50, 30, ()),], {"ligero": True}),
    ("cepillo", "Higiene bucal", "Oralys", "Oralys Cepillo Dental", "Cepillo dental de cabezal compacto",
     ["Cepillo dental de cabezal compacto y filamentos redondeados.", "El mango antideslizante facilita un cepillado cómodo.",
      "Disponible en dureza media, suave e infantil."],
     "", [], [("Adulto medio", 2.90, 40, ()), ("Adulto suave", 2.90, 35, ()), ("Infantil", 2.90, 28, ())], {"ligero": True}),
    ("champu_anticaspa", "Cuidado del cabello", "Nordavia", "Nordavia Champú Anticaspa", "Champú anticaspa para el uso frecuente",
     ["Champú anticaspa de uso frecuente que reduce las escamas y el picor del cuero cabelludo.", "Su espuma cremosa limpia sin resecar.",
      "Con extracto de menta y piroctona olamina.", "Deja el cabello suave y con aroma fresco."],
     "Aplicar sobre el cabello húmedo, masajear el cuero cabelludo, dejar actuar dos minutos y aclarar. Usar dos o tres veces por semana.",
     ["Uso externo.", "Evitar el contacto con los ojos.", "Suspender si aparece irritación."],
     [("250 ml", 9.90, 21, ("anticaspa",)), ("400 ml", 13.90, 17, ("anticaspa",))], {}),
    ("champu_graso", "Cuidado del cabello", "Nordavia", "Nordavia Champú Cabello Graso", "Champú para cabellos que se engrasan con facilidad",
     ["Champú para cabellos que se engrasan con facilidad.", "Regula el exceso de sebo y prolonga la sensación de limpieza.",
      "Con arcilla y extracto de ortiga.", "Deja el cabello ligero y con volumen."],
     "Aplicar sobre el cabello húmedo, masajear y aclarar. Repetir si es necesario.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("400 ml", 11.90, 15, ("graso",))], {}),
    ("champu_seco", "Cuidado del cabello", "Capilia", "Capilia Champú en Seco", "Champú en seco en spray",
     ["Champú en seco en spray que absorbe el exceso de grasa entre lavados.", "No deja residuos blancos y aporta volumen.", "Aroma floral."],
     "", [], [("200 ml", 6.50, 26, ()),], {"ligero": True}),
    ("mascarilla_color", "Cuidado del cabello", "Capilia", "Capilia Mascarilla Protectora del Color", "Mascarilla para cabello teñido que protege y prolonga el color",
     ["Mascarilla para cabello teñido que protege el color y prolonga su intensidad.", "Nutre la fibra capilar y aporta brillo.",
      "Con filtro UV y aceite de argán.", "Uso semanal tras el champú."],
     "Aplicar sobre el cabello húmedo y limpio, dejar actuar cinco minutos y aclarar abundantemente.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("200 ml", 14.50, 12, ("mascarilla_color",))], {}),
    ("acond_color", "Cuidado del cabello", "Capilia", "Capilia Acondicionador Cabello Teñido", "Acondicionador suave para cabello teñido o con mechas",
     ["Acondicionador suave para cabello teñido o con mechas.", "Desenreda, suaviza y ayuda a mantener el tono durante más tiempo.",
      "Sin sulfatos.", "Uso diario."],
     "Aplicar de medios a puntas tras el champú, dejar actuar un minuto y aclarar.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("250 ml", 9.50, 14, ("mascarilla_color",))], {}),
    ("mascarilla_rep", "Cuidado del cabello", "Nordavia", "Nordavia Mascarilla Reparadora", "Mascarilla nutritiva para cabello dañado",
     ["Mascarilla nutritiva para cabello seco y dañado.", "Repara las puntas abiertas y devuelve la elasticidad.", "Con manteca de karité."],
     "", [], [("200 ml", 12.50, 10, ()),], {"ligero": True}),
    ("propia_sebo", "Cuidado del cabello", MARCA_PROPIA, "Marca Ejemplo Champú Sebocorrector", "Champú sebocorrector para cabello graso",
     ["Champú sebocorrector para cuero cabelludo y cabello que se engrasan con facilidad.", "Regula la producción de sebo y prolonga la limpieza.",
      "Con extracto de abedul.", "Deja el cabello ligero y fresco."],
     "Aplicar sobre el cabello húmedo, masajear y aclarar. Uso frecuente.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("400 ml", 13.00, 18, ("pelo_propia", "graso", "marca_propia"))], {}),
    ("propia_suave", "Cuidado del cabello", MARCA_PROPIA, "Marca Ejemplo Champú Suave", "Champú suave de uso diario",
     ["Champú suave de uso diario para todo tipo de cabello.", "Limpia con delicadeza sin resecar.", "Sin parabenos."],
     "", [], [("400 ml", 13.00, 22, ("pelo_propia", "marca_propia"))], {"ligero": True}),
    ("propia_caida", "Cuidado del cabello", MARCA_PROPIA, "Marca Ejemplo Champú Anticaída", "Champú fortalecedor para cabello debilitado",
     ["Champú fortalecedor para cabello debilitado que tiende a caerse.", "Estimula el cuero cabelludo y refuerza la raíz.",
      "Con cafeína y biotina.", "Uso diario."],
     "Masajear sobre el cabello húmedo durante un minuto y aclarar.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("400 ml", 13.00, 0, ("pelo_propia", "marca_propia"))], {}),
    ("manos_intensiva", "Cuidado de manos", "Hidrovia", "Hidrovia Crema de Manos Intensiva", "Crema de manos de hidratación intensiva",
     ["Crema de manos de hidratación intensiva para pieles muy secas.", "Con urea y glicerina, alivia la sequedad y la tirantez.",
      "Se absorbe rápido y no deja sensación grasa.", "Apta para uso frecuente a lo largo del día."],
     "Aplicar sobre las manos limpias y secas y masajear hasta su completa absorción. Repetir cuantas veces sea necesario.",
     ["Uso externo.", "No aplicar sobre heridas."],
     [("50 ml", 5.95, 34, ("manos_secas", "manos")), ("100 ml", 9.50, 20, ("manos_secas", "manos"))], {}),
    ("manos_repara", "Cuidado de manos", "Hidrovia", "Hidrovia Crema de Manos Reparadora Agrietadas", "Crema reparadora para manos secas y agrietadas",
     ["Crema reparadora para manos secas y agrietadas.", "Con manteca de karité y pantenol, ayuda a regenerar la piel.",
      "Forma una película protectora frente al frío y los lavados frecuentes.", "Textura rica de rápida absorción."],
     "Aplicar por la noche y cada vez que se laven las manos.",
     ["Uso externo.", "No aplicar sobre heridas abiertas."],
     [("75 ml", 7.90, 16, ("manos_secas", "manos"))], {}),
    ("manos_ligera", "Cuidado de manos", "Pielara", "Pielara Crema de Manos Textura Ligera", "Crema de manos de textura ligera",
     ["Crema de manos de textura ligera para el uso diario.", "Hidrata sin dejar residuo y deja un aroma suave."],
     "", [], [("75 ml", 4.95, 29, ("manos",))], {"ligero": True}),
    ("balsamo", "Cuidado de manos", "Hidrovia", "Hidrovia Bálsamo Labial", "Bálsamo labial nutritivo",
     ["Bálsamo labial nutritivo que protege los labios del frío y la sequedad.", "Con manteca de cacao."],
     "", [], [("4 g", 2.50, 50, ())], {"ligero": True}),
    ("acne_gel", "Acné y piel grasa", "Pielara", "Pielara Gel Limpiador Piel Grasa", "Gel limpiador purificante para piel grasa",
     ["Gel limpiador purificante para piel grasa con tendencia acneica.", "Elimina el exceso de sebo sin agredir la piel.",
      "Con zinc y ácido salicílico.", "Uso mañana y noche."],
     "Aplicar sobre el rostro húmedo, masajear con suavidad y aclarar con agua.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("200 ml", 10.90, 14, ("acne",))], {}),
    ("acne_crema", "Acné y piel grasa", "Pielara", "Pielara Crema Matificante Anti-Imperfecciones", "Crema matificante para piel con imperfecciones",
     ["Crema matificante para piel con imperfecciones.", "Reduce el brillo y ayuda a prevenir la aparición de granos.",
      "Textura ligera no comedogénica.", "Puede usarse como base del maquillaje."],
     "Aplicar sobre el rostro limpio cada mañana y cada noche.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("40 ml", 14.90, 10, ("acne",))], {}),
    ("parches", "Acné y piel grasa", "Pielara", "Pielara Parches Anti-Granos", "Parches hidrocoloides para granos localizados",
     ["Parches hidrocoloides para cubrir granos localizados.", "Absorben el exudado y protegen la zona del roce."],
     "", [], [("24 unidades", 6.90, 18, ("acne",))], {"ligero": True}),
    ("serum_c", "Antiedad", "Pielara", "Pielara Sérum Vitamina C", "Sérum antioxidante con vitamina C",
     ["Sérum antioxidante con vitamina C estabilizada que unifica el tono y aporta luminosidad.", "Su textura fluida se absorbe rápido.",
      "Con ácido hialurónico.", "Uso por la mañana bajo la crema y el protector solar."],
     "Aplicar unas gotas sobre el rostro y el cuello limpios antes de la crema.",
     ["Uso externo.", "Conservar en lugar fresco y protegido de la luz."],
     [("30 ml", 24.90, 9, ("antiedad",))], {}),
    ("crema_noche", "Antiedad", "Pielara", "Pielara Crema de Noche Antiedad", "Crema de noche reafirmante",
     ["Crema de noche reafirmante que repara la piel mientras se duerme.", "Con retinol encapsulado y péptidos.", "Textura rica y confortable."],
     "", [], [("50 ml", 29.90, 6, ("antiedad",))], {"ligero": True}),
    ("contorno", "Antiedad", "Pielara", "Pielara Contorno de Ojos", "Contorno de ojos antiarrugas e hidratante",
     ["Contorno de ojos hidratante que atenúa las líneas de expresión.", "Su aplicador con bola metálica refresca y descongestiona."],
     "", [], [("15 ml", 17.90, 12, ("antiedad",))], {"ligero": True}),
    ("vit_c", "Vitaminas y suplementos", "Vitalora", "Vitalora Vitamina C", "Complemento alimenticio con vitamina C",
     ["Complemento alimenticio con vitamina C de liberación gradual.", "Ayuda a mantener las defensas como parte de una dieta equilibrada.",
      "Envase con 30 o 90 comprimidos.", "Sin gluten."],
     "Tomar un comprimido al día con un vaso de agua, preferiblemente con las comidas.",
     ["No exceder la cantidad diaria indicada en el envase.", "Los complementos no sustituyen a una dieta variada.", "Guardar en un sitio al que los niños no tengan acceso."],
     [("30 comprimidos", 8.90, 24, ("vitaminas",)), ("90 comprimidos", 19.90, -1, ("vitaminas",))], {}),
    ("magnesio", "Vitaminas y suplementos", "Vitalora", "Vitalora Magnesio", "Suplemento de magnesio en cápsulas",
     ["Complemento alimenticio con magnesio que contribuye al normal funcionamiento de los músculos.", "Fácil de tragar.", "Sin gluten."],
     "", [], [("60 cápsulas", 11.50, 16, ("vitaminas",))], {"ligero": True}),
    ("omega", "Vitaminas y suplementos", "Vitalora", "Vitalora Omega 3", "Complemento alimenticio con ácidos grasos omega 3",
     ["Complemento alimenticio con ácidos grasos omega 3 de origen marino.", "Contribuye al normal funcionamiento del corazón con una ingesta diaria adecuada.",
      "Cápsulas de fácil deglución.", "Sin regusto a pescado."],
     "Tomar dos cápsulas al día con una comida.",
     ["No exceder la cantidad diaria indicada en el envase.", "Guardar en un sitio al que los niños no tengan acceso."],
     [("90 cápsulas", 15.90, 11, ("vitaminas",))], {}),
    ("multi", "Vitaminas y suplementos", "Vitalora", "Vitalora Multivitamínico", "Complemento multivitamínico y mineral",
     ["Complemento multivitamínico y mineral de uso diario.", "Aporta vitaminas y minerales esenciales.", "Sin gluten."],
     "", [], [("30 comprimidos", 9.90, 19, ("vitaminas",))], {"ligero": True}),
    ("complejo_b", "Vitaminas y suplementos", "Vitalora", "Vitalora Complejo B", "Complemento con vitaminas del grupo B",
     ["Complemento con vitaminas del grupo B que contribuyen a reducir el cansancio y la fatiga.", "Envase de 60 cápsulas."],
     "", [], [("60 cápsulas", 10.50, -1, ("vitaminas",))], {"ligero": True}),
    ("lentillas", "Óptica", "Lumiara", "Lumiara Lentillas Diarias", "Lentillas de hidrogel de silicona de uso diario",
     ["Lentillas de hidrogel de silicona de uso diario con alto contenido en agua.", "Su diseño permite una buena oxigenación de la córnea.",
      "Incluyen filtro UV y borde fino para mayor comodidad.", "Caja de 30 unidades."],
     "Colocar con las manos limpias y desechar al final del día. No reutilizar.",
     ["Consultar a un profesional de la visión antes del primer uso.", "Retirar las lentillas ante cualquier molestia ocular.", "No dormir con ellas."],
     [("-1.00 30 unidades", 16.50, 14, ("lentillas",)), ("-1.50 30 unidades", 16.50, 12, ("lentillas",)),
      ("-2.00 30 unidades", 16.50, 9, ("lentillas",)), ("-2.50 30 unidades", 16.50, 0, ("lentillas",)),
      ("+1.00 30 unidades", 16.50, 6, ("lentillas",))], {}),
    ("solucion", "Óptica", "Lumiara", "Lumiara Solución Multiusos", "Solución multiusos para lentes de contacto",
     ["Solución multiusos para limpiar, desinfectar, enjuagar y conservar las lentes de contacto.", "Incluye un estuche.",
      "Fórmula con agentes hidratantes.", "Apta para lentes blandas."],
     "Enjuagar y frotar cada lente, sumergirla en la solución y dejarla en reposo al menos cuatro horas.",
     ["No ingerir.", "No utilizar si el envase está abierto desde hace más de tres meses."],
     [("360 ml", 9.50, 25, ("lentillas",)), ("100 ml", 3.90, 30, ("lentillas",))], {}),
    ("gotas", "Óptica", "Lumiara", "Lumiara Gotas Lubricantes Oculares", "Gotas lubricantes para el ojo seco",
     ["Gotas lubricantes para aliviar la sequedad ocular.", "Compatibles con lentes de contacto."],
     "", [], [("10 ml", 8.50, 15, ()),], {"ligero": True}),
    ("suero", "Higiene nasal", "Aquanta", "Aquanta Suero Fisiológico Monodosis", "Suero fisiológico en monodosis",
     ["Suero fisiológico en monodosis para la higiene de las fosas nasales y los ojos.", "Solución estéril e isotónica sin conservantes.",
      "Cada ampolla se usa una sola vez.", "Apto para bebés y adultos."],
     "Abrir la ampolla y aplicar su contenido en cada fosa nasal con la cabeza ladeada. Desechar tras el uso.",
     ["Uso externo.", "Cada monodosis es de un solo uso."],
     [("30 x 5 ml", 4.50, 38, ("suero",)), ("10 x 5 ml", 2.40, 41, ("suero",))], {}),
    ("spray_nasal", "Higiene nasal", "Aquanta", "Aquanta Spray Nasal Agua de Mar", "Spray nasal de agua de mar isotónica",
     ["Spray nasal de agua de mar isotónica para la higiene diaria de la nariz.", "Facilita la eliminación de mucosidad y polvo.",
      "Su pulverizador de microgota no irrita.", "Sin conservantes."],
     "Pulverizar una o dos veces en cada fosa nasal según necesidad.",
     ["Uso nasal.", "Uso personal: no compartir el envase."],
     [("100 ml", 6.90, 20, ("suero",))], {}),
    ("aspirador", "Higiene nasal", "Aquanta", "Aquanta Aspirador Nasal", "Aspirador nasal manual para bebés",
     ["Aspirador nasal manual para bebés con boquilla suave.", "Fácil de desmontar y limpiar."],
     "", [], [("1 unidad", 5.90, 10, ())], {"ligero": True}),
    ("barrita", "Nutrición deportiva", "Fortessa", "Fortessa Barrita Proteica", "Barrita con alto contenido en proteína",
     ["Barrita con alto contenido en proteína y bajo contenido en azúcares.", "Textura blanda con cobertura de sabor.",
      "Ideal como tentempié después del ejercicio.", "Disponible en tres sabores."],
     "Consumir una barrita como tentempié. Acompañar con agua.",
     ["Los complementos no sustituyen a una dieta variada.", "Puede contener trazas de frutos secos."],
     [("Chocolate 55 g", 2.50, 60, ("barrita",)), ("Caramelo 55 g", 2.50, 52, ("barrita",)), ("Galleta y nata 55 g", 2.50, 47, ("barrita",))], {}),
    ("batido", "Nutrición deportiva", "Fortessa", "Fortessa Batido de Proteínas", "Batido listo para beber con proteína",
     ["Batido listo para beber con alto contenido en proteína.", "Sin azúcares añadidos.", "Se conserva a temperatura ambiente."],
     "", [], [("Vainilla 330 ml", 3.20, 33, ()), ("Fresa 330 ml", 3.20, 29, ())], {"ligero": True}),
    ("termo_digital", "Dispositivos médicos", "Medinova", "Medinova Termómetro Digital", "Termómetro digital de medición rápida",
     ["Termómetro digital de medición rápida con pantalla de lectura clara.", "Señal acústica al finalizar la medición.",
      "Memoria de la última lectura.", "Resistente al agua."],
     "Encender el termómetro, colocarlo según las instrucciones y esperar la señal acústica.",
     ["Limpiar la punta antes y después de cada uso.", "Consultar las instrucciones de la batería."],
     [("Punta flexible", 7.95, 14, ("termometro",)), ("Punta rígida", 6.95, 18, ("termometro",))], {}),
    ("termo_infra", "Dispositivos médicos", "Medinova", "Medinova Termómetro Infrarrojo Frontal", "Termómetro infrarrojo sin contacto",
     ["Termómetro infrarrojo que mide la temperatura en la frente sin contacto.", "Medición en un segundo con aviso luminoso.",
      "Pantalla retroiluminada.", "Incluye funda de almacenamiento."],
     "Apuntar a la frente a pocos centímetros y pulsar el botón de medición.",
     ["No usar con la frente sudorosa o recién expuesta al frío.", "Limpiar el sensor con un paño suave."],
     [("1 unidad", 24.90, 8, ("termometro",))], {}),
    ("tensiometro", "Dispositivos médicos", "Medinova", "Medinova Tensiómetro de Brazo", "Tensiómetro digital de brazo",
     ["Tensiómetro digital de brazo con pantalla grande.", "Memoria para las últimas lecturas y detección de pulso irregular."],
     "", [], [("1 unidad", 39.90, 7, ()),], {"ligero": True}),
    ("base", "Maquillaje", "Belanova", "Belanova Base de Maquillaje Fluida", "Base de maquillaje fluida de cobertura media",
     ["Base de maquillaje fluida de cobertura media y acabado natural.", "Unifica el tono y disimula las imperfecciones.",
      "Sin perfume.", "Disponible en tres tonos."],
     "Aplicar con los dedos, una esponja o una brocha sobre el rostro limpio e hidratado.",
     ["Uso externo.", "Retirar con desmaquillante al final del día."],
     [("Tono claro", 14.50, 11, ()), ("Tono medio", 14.50, 9, ()), ("Tono oscuro", 14.50, 0, ())], {}),
    ("labial", "Maquillaje", "Belanova", "Belanova Barra de Labios Hidratante", "Barra de labios hidratante de color intenso",
     ["Barra de labios hidratante de color intenso y confort duradero.", "Con aceite de jojoba."],
     "", [], [("Rosa", 7.90, 14, ()), ("Coral", 7.90, 12, ())], {"ligero": True}),
    ("mascara", "Maquillaje", "Belanova", "Belanova Máscara de Pestañas Volumen", "Máscara de pestañas de volumen",
     ["Máscara de pestañas que aporta volumen y definición sin grumos.", "Fórmula resistente al agua."],
     "", [], [("Negro 10 ml", 9.90, 17, ())], {"ligero": True}),
    ("propia_gel", "Higiene", MARCA_PROPIA, "Marca Ejemplo Gel de Manos Higienizante", "Gel higienizante de manos de rápida evaporación",
     ["Gel higienizante de manos de rápida evaporación que no deja sensación pegajosa.", "Con glicerina para evitar la sequedad.",
      "Formato de bolsillo.", "Uso frecuente."],
     "Aplicar una cantidad suficiente sobre las manos secas y frotar hasta que se evapore.",
     ["Uso externo.", "Inflamable: mantener alejado del fuego.", "Evitar el contacto con los ojos."],
     [("100 ml", 2.90, 70, ("marca_propia",))], {}),
    ("propia_hidratante", "Cuidado facial", MARCA_PROPIA, "Marca Ejemplo Crema Hidratante Facial", "Crema hidratante facial para el uso diario",
     ["Crema hidratante facial para el uso diario.", "Con ácido hialurónico y glicerina, mantiene la piel hidratada durante todo el día.",
      "Textura ligera y sin perfume.", "Apta para pieles sensibles."],
     "Aplicar sobre el rostro y el cuello limpios, por la mañana y por la noche.",
     ["Uso externo.", "Evitar el contacto con los ojos."],
     [("50 ml", 9.90, 26, ("marca_propia",))], {}),
    ("propia_toallitas", "Higiene", MARCA_PROPIA, "Marca Ejemplo Toallitas Desmaquillantes", "Toallitas desmaquillantes suaves",
     ["Toallitas desmaquillantes suaves que eliminan el maquillaje y las impurezas.", "Sin alcohol."],
     "", [], [("25 unidades", 3.50, 0, ("marca_propia",))], {"ligero": True}),
]

# Productos con defectos de ficha: (clave de defecto, categoría, marca, nombre, precio, stock, contenido extra)
DEFECTOS = [
    ("sin_descripcion", "Protección solar", "Solenza", "Solenza Barra Solar Mini 15 g", 5.50, 7, {}),
    ("sin_descripcion", "Maquillaje", "Belanova", "Belanova Esmalte de Uñas Rojo", 4.90, 12, {}),
    ("sin_descripcion", "Cuidado del cabello", "Capilia", "Capilia Gorro de Ducha", 1.90, 30, {}),
    ("sin_descripcion", "Dispositivos médicos", "Medinova", "Medinova Pilas de Botón para Termómetro", 2.50, 0, {}),
    ("sin_descripcion", "Regalo", None, "Bolsa de Regalo Pequeña", 0.50, 100, {}),
    ("sin_descripcion", "Vitaminas y suplementos", "Vitalora", "Vitalora Pastillero Semanal", 3.90, 15, {}),
    ("repite_nombre", "Higiene bucal", "Oralys", "Oralys Enjuague Bucal Menta 250 ml", 4.20, 22, {}),
    ("repite_nombre", "Cuidado de manos", "Hidrovia", "Hidrovia Jabón de Manos Neutro 300 ml", 3.40, 18, {}),
    ("repite_nombre", "Higiene nasal", "Aquanta", "Aquanta Gotas Nasales Niños 10 ml", 5.20, 9, {}),
    ("repite_nombre", "Cuidado del cabello", "Nordavia", "Nordavia Peine Desenredante", 4.50, 5, {}),
    ("basura", "Cuidado del bebé", "Kiddora", "Kiddora Bolsa de Pañales de Viaje", 9.90, 4,
     {"desc": "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore."}),
    ("basura", "Maquillaje", "Belanova", "Belanova Pincel de Maquillaje", 6.50, 10, {"desc": "Lorem ipsum dolor sit amet"}),
    ("basura", "Nutrición deportiva", "Fortessa", "Fortessa Coctelera Deportiva 500 ml", 8.95, 6,
     {"corta": "Traduzir esta descrição para português de Portugal",
      "desc": "Coctelera de 500 ml con tapa antiderrames y bola mezcladora de acero inoxidable. Apta para lavavajillas y sin bisfenol A."}),
    ("basura", "Cuidado facial", "Pielara", "Pielara Espejo de Aumento", 11.90, 3, {"desc": "Texto pendiente de completar"}),
    ("basura", "Óptica", "Lumiara", "Lumiara Estuche de Lentillas", 2.90, 40, {"desc": "xxxxxx"}),
]
INACTIVOS = [
    ("Solenza", "Solenza Fluido Facial Solar SPF 15 50 ml (descatalogado)"),
    ("Kiddora", "Kiddora Crema Solar Bebé Antigua Fórmula"),
    ("Oralys", "Oralys Colutorio Sabor Fresa 250 ml"),
    ("Nordavia", "Nordavia Champú Edición Limitada"),
    ("Hidrovia", "Hidrovia Crema de Manos Pack Regalo 2019"),
    ("Vitalora", "Vitalora Vitamina D Gominolas"),
    ("Belanova", "Belanova Paleta de Sombras Otoño"),
    ("Pielara", "Pielara Exfoliante Facial Antiguo"),
]

INTENCIONES = [
    ("protector solar para niños", "sol_ninos"),
    ("algo para la boca seca", "boca_seca"),
    ("champú anticaspa", "anticaspa"),
    ("crema de manos para piel muy seca", "manos_secas"),
    ("lentillas diarias", "lentillas"),
    ("suero fisiológico", "suero"),
    ("barrita de proteínas", "barrita"),
    ("termómetro", "termometro"),
    ("crema para piel atópica de bebé", "atopica"),
    ("mascarilla para cabello teñido", "mascarilla_color"),
    ("productos de Farmacia Ejemplo para el pelo", "pelo_propia"),
    ("crema para el culito del bebé con irritación del pañal", "panal"),
    ("protector solar facial", "sol_facial"),
    ("vitamina C", "vitaminas"),
]


# ----------------------------------------------------------------------------------------------------------------
def slug(texto):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def ean13(rng):
    """EAN-13 con prefijo 200 (rango de uso interno): válido pero nunca un código de producto real."""
    d = "200" + "".join(str(rng.randint(0, 9)) for _ in range(9))
    suma = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d))
    return d + str((10 - suma % 10) % 10)


def variante_marca(marca, rng, propia):
    """La marca tal como sale de la base de datos: mayúsculas inconsistentes y alguna variante de nombre."""
    if marca is None:
        return ""
    if propia:
        return rng.choice([MARCA_PROPIA.upper(), MARCA_PROPIA, MARCA_PROPIA.lower()])
    opciones = [marca.upper(), marca.upper(), marca, marca.lower(), marca + " "]
    if marca == "Solenza":
        opciones.append("SOLENZA ESPAÑA")
    return rng.choice(opciones)


def html_ficha(nombre, frases, modo, prec, estilo, rng):
    """Ficha en HTML con el ruido típico de una base de datos de tienda online."""
    d = " ".join(frases)
    p = " ".join(prec)
    li = "".join(f"<li>{x}</li>" for x in prec)
    if estilo == "secciones_p":
        return ('<p style="text-align: justify;"><strong>DESCRIPCIÓN</strong></p>'
                f'<p style="text-align: justify;">{d}</p>'
                + (f'<p style="text-align: justify;"><strong>MODO DE EMPLEO</strong></p><p style="text-align: justify;">{modo}</p>' if modo else "")
                + (f'<p style="text-align: justify;"><strong>PRECAUCIONES Y ADVERTENCIAS</strong></p><ul>{li}</ul>' if prec else ""))
    if estilo == "b_br":
        return ('<div style="text-align:justify;"><br /><b>ACCIÓN Y DESCRIPCIÓN</b><br />' + d
                + (f"<br /><br /><b>MODO DE USO</b><br />{modo}" if modo else "")
                + (f"<br /><br /><b>ADVERTENCIAS</b><br />{p}" if prec else "") + "</div>")
    if estilo == "nombre_primero":
        return (f"<p>{nombre}</p><p>{d}</p>"
                + (f"<p><strong>Modo de empleo:</strong> {modo}</p>" if modo else "")
                + (f"<p><strong>Precauciones:</strong> {p}</p>" if prec else ""))
    if estilo == "entidades":
        t = d.replace("ó", "&oacute;").replace("í", "&iacute;").replace("á", "&aacute;").replace(". ", ".&nbsp; ")
        return (f"<p>{t}</p>" + (f"<p><strong>MODO&nbsp;DE EMPLEO</strong><br />{modo.replace('ó', '&oacute;')}</p>" if modo else "")
                + (f"<p><strong>PRECAUCIONES</strong><br />{p}</p>" if prec else ""))
    if estilo == "documento":
        return ('<html><head><title></title> </head> <body bgcolor="#f0f0f0"> <font size=3 face="Verdana"> <div align=justify>'
                f"<br><b>{nombre}</b></div> <div align=justify><br>{d}<br><br><b>MODO DE EMPLEO</b><br>{modo}</div> </font> </body></html>"
                if modo else f"<p>{d}</p>")
    return f"<p>{d}</p>"  # plano


ESTILOS = ["secciones_p", "secciones_p", "b_br", "nombre_primero", "entidades", "documento"]


RELLENO = [
    "Fabricado bajo estrictos controles de calidad.",
    "El envase es reciclable y su tapa garantiza un cierre seguro.",
    "Formulado sin parabenos ni colorantes artificiales.",
    "Conservar en un lugar fresco y seco, protegido de la luz solar directa.",
    "Una vez abierto, consumir en el plazo indicado en el envase.",
    "Producto pensado para acompañar la rutina diaria de toda la familia.",
]


def ampliar(frases, rng, minimo=340):
    """Añade frases genéricas hasta que la ficha larga supere el umbral de nivel 'completa' (300 caracteres)."""
    frases, pool = list(frases), RELLENO[:]
    rng.shuffle(pool)
    while len(" ".join(frases)) < minimo and pool:
        frases.append(pool.pop())
    return frases


def nombre_ruidoso(nombre, rng):
    """Nombre tal como sale de la exportación de productos: a veces en mayúsculas o con espacios de más."""
    r = rng.random()
    if r < 0.12:
        return nombre.upper()
    if r < 0.22:
        return nombre.replace(" ", "  ", 1)
    if r < 0.27:
        return nombre + " "
    return nombre


def construir(rng):
    productos, pid = [], PRIMER_ID

    def nuevo(categoria, marca, nombre, precio, stock, tags, desc_html, corta_html, propia=False):
        nonlocal pid
        productos.append({
            "id": pid, "categoria": categoria, "marca_limpia": marca, "marca_raw": variante_marca(marca, rng, propia or marca == MARCA_PROPIA),
            "nombre": nombre, "precio": precio, "stock": stock, "tags": set(tags), "desc_html": desc_html, "corta_html": corta_html,
            "ean13": ean13(rng), "referencia": f"{rng.randint(0, 999999):06d}", "activo": 1,
        })
        pid += 1

    for clave, categoria, marca, base, corta, frases, modo, prec, variantes, opc in FAMILIAS:
        ligero = opc.get("ligero", False)
        estilo = "plano" if ligero else rng.choice(ESTILOS)
        if not ligero:
            frases = ampliar(frases, rng)
        for sufijo, precio, stock, tags in variantes:
            nombre = f"{base} {sufijo}"
            desc = html_ficha(nombre, frases[:2] if ligero else frases, modo, prec, estilo, rng)
            nuevo(categoria, marca, nombre, precio, stock, tags, desc, rng.choice([f"<p>{corta}</p>", corta]))
    for tipo, categoria, marca, nombre, precio, stock, extra in DEFECTOS:
        if tipo == "sin_descripcion":
            desc, corta = None, None
        elif tipo == "repite_nombre":
            desc, corta = f"<p>{nombre}</p>", None
        else:  # basura
            desc, corta = extra.get("desc"), extra.get("corta")
            desc = f"<p>{desc}</p>" if desc else None
        nuevo(categoria, marca, nombre, precio, stock, (), desc, corta)

    inactivos = []
    for i, (marca, nombre) in enumerate(INACTIVOS):
        inactivos.append({"id": 901 + i, "nombre": nombre, "marca_raw": variante_marca(marca, rng, False), "ean13": ean13(rng),
                          "referencia": f"{rng.randint(0, 999999):06d}"})
    return productos, inactivos


def escribir_csv(productos, inactivos, rng):
    CRUDO.mkdir(parents=True, exist_ok=True)
    cab_prod = ["Product ID", "Imagen", "Nombre", "Referencia", "Categoría", "Precio (imp. excl.)", "Precio (imp. incl.)", "Cantidad", "Estado", "Posición"]
    with open(CRUDO / "productos_ejemplo.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(cab_prod)
        for p in productos:
            categoria = "" if rng.random() < 0.04 else p["categoria"]  # algún producto sin categoría
            w.writerow([p["id"], f"/placeholder/{p['id']}.svg", nombre_ruidoso(p["nombre"], rng), p["referencia"], categoria,
                        f"{p['precio'] / IVA:.6f}", p["precio"], p["stock"], 0 if p["stock"] > 0 else 1, ""])
    cab_sql = ["id_product", "reference", "ean13", "active", "name", "description_short", "description", "link_rewrite", "marca"]
    with open(CRUDO / "export_sql_ejemplo.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(cab_sql)
        for p in productos:
            w.writerow([p["id"], p["referencia"], p["ean13"], 1, p["nombre"], p["corta_html"] or "", p["desc_html"] or "",
                        f"{slug(p['nombre'])}-{p['referencia']}", p["marca_raw"]])
        for p in inactivos:  # solo están en la exportación SQL, no en la de productos
            w.writerow([p["id"], p["referencia"], p["ean13"], 0, p["nombre"], "", "", f"{slug(p['nombre'])}-{p['referencia']}", p["marca_raw"]])


def escribir_evaluacion(productos):
    casos = []
    for consulta, etiqueta in INTENCIONES:
        ids = [p["id"] for p in productos if etiqueta in p["tags"] and p["stock"] > 0]  # solo con stock: el buscador filtra por defecto
        casos.append({"consulta": consulta, "ids_esperados": ids})
    (config.BASE / "evaluacion.json").write_text(json.dumps(casos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return casos


def main(semilla):
    rng = random.Random(semilla)
    productos, inactivos = construir(rng)
    escribir_csv(productos, inactivos, rng)
    convertir_json.convertir()
    crudo, ignorados = fusionar_sql.fusionar()
    _, limpio = limpiar_catalogo.limpiar()
    casos = escribir_evaluacion(productos)

    n = len(limpio)
    resumen = {
        "productos": n, "inactivos solo en la exportación SQL": ignorados,
        "sin descripción": sum(r["descripcion"] is None for r in limpio),
        "marcados para revisar (texto basura)": sum(r["revisar"] for r in limpio),
        "sin stock": sum(r["stock"] == 0 for r in limpio), "stock negativo": sum(r["stock"] < 0 for r in limpio),
        "marca propia": sum(r["marca_propia"] for r in limpio), "sin marca": sum(r["marca"] is None for r in limpio),
        "marcas en crudo → normalizadas": f"{len({r['marca'] for r in crudo if r['marca']})} → {len({r['marca'] for r in limpio if r['marca']})}",
        "nivel_info": {k: sum(r["nivel_info"] == k for r in limpio) for k in ("completa", "parcial", "minima")},
        "con modo_empleo / precauciones": f"{sum(bool(r['modo_empleo']) for r in limpio)} / {sum(bool(r['precauciones']) for r in limpio)}",
    }
    print(f"Catálogo de ejemplo generado con semilla {semilla}:")
    for k, v in resumen.items():
        print(f"  {k}: {v}")
    print(f"  evaluacion.json: {len(casos)} consultas")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--semilla", type=int, default=42)
    main(ap.parse_args().semilla)
