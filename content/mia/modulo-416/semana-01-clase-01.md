---
title: "Fundamentos de Visualización de Datos y Modelado Dimensional"
description: "Semana 1 · Clase 1 · DATA VISUALIZATION AND VISUAL ANALYTICS"
academic: true
program: "MIA"
module: "DATA VISUALIZATION AND VISUAL ANALYTICS"
module_number: 7
session_id: null
label: "Semana 1 · Clase 1"
week: 1
class_in_week: 1
number: 1
date: null
revision: 1
content_hash: "d9d60afd2bfeca22df066463aeaf3361059ed257ea4888985a280ece6134a864"
link: "/mia/modulo-416/semana-01-clase-01.html"
download: "/notes/mia/modulo-416/semana-01-clase-01.md"
note_id: "notion:4eb142cdef5ee1ed33c1f8f9ab43ae97026c3c041a3387d843e5dc6a30f23839"
source: "notion"
prev: false
next: {"text": "Semana 1 · Clase 2", "link": "/mia/modulo-416/semana-01-clase-02.html"}
---

> **Objetivo de la Sesión**<br>
> 
> 
> Comprender el rol estratégico de la visualización de datos como interfaz entre la ingeniería técnica y la toma de decisiones empresariales, dominar los principios cognitivos de la percepción visual y aplicar los fundamentos prácticos del modelado dimensional (Star Schema) mediante herramientas de autoservicio en Power BI.

---
# Clase 1: Fundamentos de Visualización de Datos y Modelado Dimensional

## 1\. Contexto y Arquitectura: La Capa de Presentación en Datos

### 1.1. Ubicación en el Ciclo de Vida de los Datos

Dentro de la ingeniería y gestión de datos (*Data Engineering &amp; Business Intelligence*), la visualización representa la **capa final de presentación / reporting (Data Visualization &amp; Analytics)**. Previo a esta etapa se encuentran:

1. **Fuentes operacionales (OLTP):** Bases de datos relacionales transaccionales, APIs, sistemas CRM/ERP.

1. **Ingeniería e integración (ETL / ELT):** Procesos de extracción, transformación, limpieza y carga de datos.

1. **Almacenamiento analítico (OLAP / Data Warehouse):** Esquemas dimensionales, tablas de hechos y dimensiones consolidadas.

1. **Capa semántica / Modelado:** Definición de métricas de negocio, medidas calculadas y relaciones lógicas.

1. **Capa de Visualización y Consumo:** Dashboards ejecutivos, reportes analíticos interactivos y narrativa de datos (*Data Storytelling*).

### 1.2. Analogía: Data Visualization es al Dato lo que UI/UX es al Software

En el desarrollo de software convencional, una arquitectura robusta de microservicios y bases de datos resulta inútil si la interfaz de usuario (**UI**) y la experiencia de usuario (**UX**) son deficientes o incomprensibles. En analítica de datos ocurre el mismo fenómeno:

- **La interfaz del dato:** El dashboard es la interfaz a través de la cual los directivos, gerentes y tomadores de decisiones interactúan con la realidad operativa y financiera de la organización.

- **Roles interdisciplinarios:** A diferencia de las capas técnicas de ingeniería (DBAs, ingenieros de datos), la capa analítica involucra perfiles de negocio (Data Analysts, Business Analysts, administradores de empresas, economistas) cuyo valor radica en el entendimiento profundo del modelo comercial y los indicadores clave (KPIs).

### 1.3. Ecosistema Tecnológico y el Cuadrante de Gartner

La selección de herramientas analíticas empresariales responde a criterios de madurez, gobernanza y capacidad de ejecución. Según el **Cuadrante Mágico de Gartner para Plataformas de Analítica y BI**:

- **Líderes de Mercado:**

  - **Microsoft Power BI:** Amplia adopción, bajo costo relativo, integración nativa con el ecosistema empresarial, motor tabular en memoria (*VertiPaq*) y lenguaje DAX.
  
  - **Tableau (Salesforce):** Gran potencia analítica y flexibilidad en diseño visual avanzado.

- **Retadores y Alternativas Relevantes:**

  - **Google Looker Studio / Looker:** Integración nativa en Google Cloud y visualización ágil en entornos web.
  
  - **Qlik (QlikView / Qlik Sense):** Motor asociativo en memoria para exploración libre de datos.
  
  - **AWS QuickSight:** Solución nativa en la nube de Amazon orientada a escalabilidad y embebido de dashboards.
  
  - **Soluciones Corporativas Tradicionales:** SAP Analytics Cloud, MicroStrategy (soluciones potentes pero con altos costos de licenciamiento e infraestructura).

---

## 2\. Psicología y Principios de la Percepción Visual en Datos

### 2.1. ¿Por qué Visualizamos?

El propósito primario de la visualización es **comunicar** grandes volúmenes de datos complejos a audiencias no técnicas de forma inmediata, precisa y accionable.

### 2.2. Detección de Patrones vs. Carga de Datos Granulares

- **El cerebro humano no procesa matrices numéricas:** Enfrentado a listados transaccionales de miles de filas, el cerebro se satura y es incapaz de inferir conclusiones.

- **Procesamiento preatentivo y detección de formas:** El cerebro humano está biológicamente optimizado para reconocer **patrones visuales**: picos máximos, caídas abruptas, estacionalidades cíclicas, agrupaciones (*clusters*) y anomalías (*outliers*).

- **Reportes Operativos vs. Reportes Analíticos:**

  - *Reportes Operativos:* Listados detallados de soporte transaccional (ej. auditoría de facturas del día). Su consumo es técnico/administrativo puntual.
  
  - *Reportes Analíticos / Estratégicos:* Síntesis visual mediante agregaciones y KPIs destinados a responder preguntas estratégicas de negocio.

### 2.3. La Centralidad de la Dimensión Tiempo

En el 99.9% de los modelos de negocio, los hechos analizados se distribuyen en una **línea de tiempo**. La dimensión temporal permite:

- Evaluar rendimientos históricos (gestión actual vs. gestión anterior: YoY, MoM).

- Identificar estacionalidades comerciales críticas (ej. picos de venta en Black Friday, fiestas de fin de año, o caídas en periodos invernales).

- Analizar el desempeño y productividad sostenida de colaboradores, productos y sucursales.

### 2.4. Integridad de Datos: El Cuarteto de Anscombe y el Datasaurus Dozen

> **La trampa de confiar únicamente en estadísticas resumidas**<br>
> 
> 
> Conjuntos de datos con la misma media, mediana, varianza y coeficiente de correlación pueden tener distribuciones espaciales y comportamientos radicalmente diferentes cuando se grafican.

- **Cuarteto de Anscombe (1973):** Cuatro conjuntos de datos bidimensionales con propiedades estadísticas idénticas que, al graficarse, revelan comportamientos totalmente distintos (relación lineal simple, curva cuadrática, valores atípicos dominantes).

- **Datasaurus Dozen (Alberto Cairo / Justin Matejka &amp; George Fitzmaurice):** Demuestra cómo datos que comparten idénticas métricas resumen pueden formar desde círculos y estrellas hasta la figura explícita de un dinosaurio.

- **Lección analítica:** Antes de modelar y diseñar dashboards, es mandatorio realizar una **exploración visual inicial** para comprobar la dispersión real, la veracidad y la consistencia de los datos, evitando asumir que las medidas descriptivas básicas capturan toda la verdad.

### 2.5. Perspectiva de Negocio vs. Perspectiva Técnica

- A los comités ejecutivos y directivos no les impresiona la sofisticación técnica del pipeline (si se utilizó SQL Server, Snowflake o Kafka). Les importa si los números son **reales, comprensibles y accionables**.

- **El experto de dominio como validador supremo:** El personal que conoce la operación cotidiana (ventas, logística, atención telefónica) suele identificar inconsistencias en los reportes con mucha mayor rapidez que el ingeniero técnico o el equipo de QA (ej. llamadas mal fechadas en campañas clave como San Valentín o Día de la Madre).

---

## 3\. Codificación Visual, Selección de Gráficos y Sobrecarga Cognitiva

### 3.1. Parámetros de Codificación Visual

Para representar atributos de datos se emplean diversas variables visuales:

- **Posición espacial:** La codificación más precisa para comparar magnitudes numéricas (ejes X e Y).

- **Longitud y altura:** Base de los gráficos de barras y columnas.

- **Color y saturación:** Útil para categorizaciones (matiz) o intensidad/magnitud de métricas (saturación/gradiente en mapas de calor).

- **Tamaño / Área:** Usado en gráficos de burbujas (debe interpretarse con cautela por la distorsión del área vs. radio).

- **Ángulo:** Base de gráficos circulares / de dona (menor precisión perceptiva).

### 3.2. Análisis Comparativo: Caso Retrasos del Ferrocarril de Londres

Un mismo conjunto de datos (retrasos y cancelaciones en periodos de 4 semanas a lo largo de varios años) puede generar comprensiones completamente distintas según el gráfico elegido:

| Tipo de Visualización | Comportamiento Observado | Efectividad de Comunicación |
| --- | --- | --- |
| Gráfico de Dispersión (Scatter Plot) | Nube densa de puntos en el tiempo. | Baja: Demanda esfuerzo cognitivo considerable identificar el punto crítico o deducir una tendencia. |
| Gráfico de Líneas Temporales | Línea continua con picos pronunciados. | Alta: Hace evidente de forma inmediata el pico histórico crítico (14% en 2001) que exige investigación. |
| Gráfico de Burbujas / Segmentado | Burbujas en ejes modificados por periodicidad anual. | Media: Permite comparar magnitudes, pero puede saturar si el solapamiento es excesivo. |
| Mapa de Calor (Heatmap Matriz) | Matriz de años vs. periodos estacionales con gradiente de color. | Muy Alta para Contexto: Revela no solo el pico aislado de 2001, sino el patrón cíclico anual (estacionalidad en otoño/invierno y caídas en periodos fríos). |

### 3.3. Sobrecarga Cognitiva (*Cognitive Load*)

- El exceso de líneas, ejes superpuestos, colores estridentes y elementos decorativos sin propósito genera **ruido visual** (*chartjunk*).

- La regla de oro del diseño analítico: **Menos es más**. Toda tinta en la pantalla debe tener una justificación informativa directa que asista al tomador de decisiones.

### 3.4. Cuadro de Mando Integral (Executive Dashboard)

- **La cabina del piloto:** El cuadro de mando integral sintetiza el estado de la organización en un solo panel visual.

- **Componentes clave:**

  - **Tarjetas de KPI con semáforos:** Estado respecto a metas (verde = en objetivo, amarillo = alerta preventiva, rojo = desviación crítica).
  
  - **Gráficos de tendencia temporal:** Líneas o barras para evaluar la trayectoria del negocio.
  
  - **Mapas geográficos:** Distribución territorial por sucursales, regiones o países para detectar disparidades de mercado.
  
  - **Filtros interactivos:** Segmentadores por periodo, categoría o responsable comercial.

### 3.5. Tipos de Datos: Cuantitativos vs. Cualitativos Nominales

- **Medidas cuantitativas (Measures):** Cantidades vendidas, precio unitario, ingresos brutos, descuentos, ingresos netos, márgenes operativos.

- **Variables cualitativas / nominales calculadas:** Clasificaciones de negocio creadas sobre los datos para segmentar el análisis (ej. pedidos clasificados como *Venta Mayorista / Venta Minorista* según el umbral de unidades vendidas).

---

## 4\. Laboratorio Práctico: Modelado Dimensional y Autoservicio en Power BI

### 4.1. Concepto de BI de Autoservicio (*Self-Service BI*)

El analista moderno no depende de que el área de infraestructura cree un pipeline ETL rígido para cada exploración analítica. Las herramientas como Power BI permiten integrar, limpiar, combinar y modelar datos provenientes de fuentes diversas en un entorno controlado y ágil.

### 4.2. Las Tres Capas de Trabajo en Power BI

1. **Editor de Power Query (ETL y Preparación de Datos):** Transformación visual de tablas mediante pasos aplicados generados en lenguaje M.

1. **Vista de Modelo (Esquema Semántico y Relaciones):** Definición de relaciones dimensionales (1 a varios), cardinalidad, dirección de filtros y medidas calculadas en DAX.

1. **Vista de Informe (Lienzo de Visualización):** Construcción del dashboard interactivo con gráficos, tarjetas, matrices y filtros.

### 4.3. Flujo Práctico de Modelado Estrella desde Archivos Planos (CSV)

En la demostración práctica de clase se ilustró cómo construir un **Modelo Estrella (Star Schema)** partiendo exclusivamente de archivos CSV sin requerir un motor relacional previo:

#### Paso 1: Importación de Tablas Dimensionales Básicas

- Importación de ` Stores ` (Tiendas), ` Staff ` (Empleados) y ` Customers ` (Clientes).

- Validación estricta de tipos de datos en los identificadores clave (` Store_ID `, ` Staff_ID `, ` Customer_ID ` como enteros).

#### Paso 2: Desnormalización en Power Query mediante Combinación de Consultas (*Merge*)

- La tabla original de productos contiene únicamente ` Brand_ID ` y ` Category_ID `.

- En lugar de mantener una estructura copo de nieve (*Snowflake*), se utiliza la operación **Combinar Consultas (Merge)**:

  - ` Products ` ⨝ ` Brands ` sobre ` Brand_ID ` (Inner Join) ➔ Extracción de ` Brand_Name `.
  
  - ` Products ` ⨝ ` Categories ` sobre ` Category_ID ` (Inner Join) ➔ Extracción de ` Category_Name `.

- Se deshabilitan las consultas intermedias de marcas y categorías para que no se carguen innecesariamente en el modelo en memoria.

#### Paso 3: Consolidación de la Tabla de Hechos (*Fact Table*)

- Para registrar las transacciones de venta existen dos tablas: cabecera (` Orders `) y detalle (` Order Items `).

- **Criterio de granularidad:** Se selecciona la tabla de mayor granularidad (` Order Items `) como base.

- Se combinan los atributos de cabecera (` Order_Date `, ` Customer_ID `, ` Store_ID `, ` Staff_ID `) en la tabla de detalle.

- La tabla resultante consolidada contiene la métrica a nivel de ítem: ` Quantity `, ` List_Price `, ` Discount `, vinculada a todas las dimensiones del negocio.

#### Paso 4: Creación de la Clave Sintética de Fecha (` DateKey `)

- Para vincular la tabla de hechos con la dimensión ` Tiempo ` (*Date Dimension*):

  - Se transforma la fecha transaccional en un número entero serializado con formato estándar ` YYYYMMDD ` (ej. ` 2026-03-23 ` ➔ ` 20260323 `).
  
  - Esta clave permite un rendimiento óptimo de filtrado e indexación en el motor columnar *VertiPaq*.

#### Paso 5: Validación de Integridad Referencial

> **Regla Crítica de Integridad en Relaciones Dimensionales**<br>
> 
> 
> Para que Power BI cree y mantenga una relación unidireccional de 1 a Varios (1:N) entre una Dimensión y la Tabla de Hechos:
> 
> 1. Los identificadores deben compartir el **mismo tipo de dato** (entero con entero).
> 
> 1. **Consistencia de dominio:** No pueden existir valores huérfanos en la tabla de hechos (por ejemplo, una venta asociada a ` Store_ID = 4 ` si en la dimensión ` Stores ` únicamente existen las tiendas 1, 2 y 3).

---

## 5\. Hoja de Ruta del Módulo (4 Semanas)

| Fase / Semana | Enfoque Temático | Hito / Entregable Clave |
| --- | --- | --- |
| Semana 1 | Fundamentos de visualización, codificación visual y exploración de datos del negocio. | Selección y validación del caso de estudio y dataset analítico con dimensión temporal. |
| Semana 2 | Modelado dimensional en Power BI y definición de lógica analítica. | Implementación del Modelo Estrella (Star Schema), tablas de hechos, dimensiones y métricas DAX. |
| Semana 3 | Diseño de reportes analíticos efectivos, branding corporativo y UX. | Suite interactiva de dashboards por áreas de negocio con navegación y drill-down. |
| Semana 4 | Data Storytelling y narrativa ejecutiva. | Presentación y defensa ejecutiva de hallazgos ante una simulación de mesa directiva corporativa. |

---

---
