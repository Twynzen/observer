"""
🔍 Observer Bot Mejorado - Análisis Inteligente de Discord
Versión con botones interactivos para navegación fluida
"""

import discord
from discord.ext import commands
import asyncio
import openai
import os
import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
import unicodedata

# ============= CONFIGURACIÓN =============
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not DISCORD_TOKEN or not OPENAI_API_KEY:
    print("❌ ERROR: Necesitas crear un archivo .env con:")
    print("DISCORD_TOKEN=tu_token_aqui")
    print("OPENAI_API_KEY=tu_api_key_aqui")
    exit(1)

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# Importar httpx para requests asíncronos
try:
    import httpx
except ImportError:
    print("⚠️ Instalando httpx para mejores requests asíncronos...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx

# ============= CLASES PRINCIPALES =============

class CanalInfo:
    """Información básica de un canal"""
    def __init__(self, id, nombre, numero, tipo='texto'):
        self.id = id
        self.nombre = nombre
        self.numero = numero
        self.tipo = tipo
        self.nombre_normalizado = self.normalizar_nombre(nombre)
    
    def normalizar_nombre(self, texto):
        """Normaliza nombres con caracteres Unicode"""
        # Convertir caracteres Unicode fancy a ASCII normal
        texto_normalizado = unicodedata.normalize('NFKD', texto)
        texto_normalizado = texto_normalizado.encode('ascii', 'ignore').decode('ascii')
        # Si queda vacío después de normalizar, usar el original
        if not texto_normalizado.strip():
            texto_normalizado = texto.lower()
        return texto_normalizado.lower().replace('-', ' ').replace('_', ' ').strip()

# ============= VISTAS INTERACTIVAS =============

class HilosSelect(discord.ui.Select):
    """Dropdown para seleccionar hilos"""
    def __init__(self, bot, hilos, analyzer):
        self.bot = bot
        self.analyzer = analyzer
        options = []
        for hilo in hilos[:25]:  # Límite de Discord
            options.append(discord.SelectOption(
                label=hilo['nombre'][:100],
                value=str(hilo['id']),
                description=f"{hilo.get('mensajes', 0)} mensajes",
                emoji="🧵"
            ))
        
        super().__init__(
            placeholder="📎 Analizar un hilo relacionado...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        try:
            hilo_id = int(self.values[0])
            
            # Obtener el hilo
            hilo = interaction.guild.get_thread(hilo_id)
            if not hilo:
                hilo = interaction.guild.get_channel(hilo_id)  # Intentar como canal normal
            
            if not hilo:
                await interaction.response.send_message("❌ No puedo acceder a ese hilo.", ephemeral=True)
                return
            
            # Responder primero para evitar timeout
            await interaction.response.send_message(f"🔍 **Analizando hilo** {hilo.name}...", ephemeral=False)
            
            # Analizar el hilo
            analisis = await self.analyzer.analizar_canal(hilo)
            
            # Crear embed con resultados
            embed = self.bot.crear_embed_analisis(analisis, es_hilo=True)
            
            # Crear nueva vista si el análisis tiene hilos o más eventos
            nueva_view = None
            if (analisis.get('canales_relacionados', {}).get('hilos_activos') or 
                analisis.get('num_eventos', 0) > 5):
                # Crear CanalInfo temporal para el hilo
                canal_info_hilo = CanalInfo(
                    id=hilo.id,
                    nombre=hilo.name,
                    numero=0,  # No importa el número aquí
                    tipo='hilo'
                )
                nueva_view = AnalisisView(self.bot, analisis, canal_info_hilo)
            
            # Editar el mensaje con los resultados
            await interaction.edit_original_response(content=None, embed=embed, view=nueva_view)
            
        except Exception as e:
            print(f"Error en HilosSelect: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Error al analizar: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Error al analizar: {str(e)}", ephemeral=True)

class VerMasEventosButton(discord.ui.Button):
    """Botón para ver más eventos"""
    def __init__(self, canal_info, analisis_data, pagina_eventos=0):
        super().__init__(
            label="Ver más eventos",
            style=discord.ButtonStyle.primary,
            emoji="📊"
        )
        self.canal_info = canal_info
        self.analisis_data = analisis_data
        self.pagina_eventos = pagina_eventos
        self.eventos_por_pagina = 5
    
    async def callback(self, interaction: discord.Interaction):
        try:
            self.pagina_eventos += 1
            
            # Calcular eventos a mostrar
            inicio = self.pagina_eventos * self.eventos_por_pagina
            fin = inicio + self.eventos_por_pagina
            eventos = self.analisis_data['eventos'][inicio:fin]
            
            if not eventos:
                await interaction.response.send_message("No hay más eventos para mostrar.", ephemeral=True)
                return
            
            # Crear embed con más eventos
            embed = discord.Embed(
                title=f"📊 Más eventos de #{self.canal_info.nombre} (Página {self.pagina_eventos + 1})",
                color=0x00ff00
            )
            
            eventos_texto = []
            for i, evento in enumerate(eventos, inicio + 1):
                desc = evento['descripcion'][:80]
                tipo = evento['tipo'].title()
                
                if evento.get('mensaje_url'):
                    evento_str = f"**{i}. {tipo}**: [{desc}...]({evento['mensaje_url']})"
                else:
                    evento_str = f"**{i}. {tipo}**: {desc}..."
                
                if evento.get('participantes'):
                    evento_str += f"\n👥 *{', '.join(evento['participantes'][:3])}*"
                
                eventos_texto.append(evento_str)
            
            embed.description = '\n\n'.join(eventos_texto)
            
            # Indicar si hay más
            total_eventos = len(self.analisis_data['eventos'])
            if fin < total_eventos:
                embed.set_footer(text=f"Mostrando {inicio+1}-{fin} de {total_eventos} eventos")
            
            await interaction.response.send_message(embed=embed, ephemeral=False)
            
        except Exception as e:
            print(f"Error en VerMasEventosButton: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)

class ActualizarButton(discord.ui.Button):
    """Botón para actualizar el análisis"""
    def __init__(self, bot, canal_info, analyzer):
        super().__init__(
            label="Actualizar análisis",
            style=discord.ButtonStyle.secondary,
            emoji="🔄"
        )
        self.bot = bot
        self.canal_info = canal_info
        self.analyzer = analyzer
    
    async def callback(self, interaction: discord.Interaction):
        try:
            # Responder primero
            await interaction.response.defer()
            
            # Limpiar caché
            if self.canal_info.id in self.analyzer.analisis_cache:
                del self.analyzer.analisis_cache[self.canal_info.id]
            
            # Re-analizar
            channel = interaction.guild.get_channel(self.canal_info.id)
            if not channel:
                await interaction.followup.send("❌ No puedo acceder a ese canal.", ephemeral=True)
                return
            
            # Mensaje de estado
            await interaction.followup.send(f"🔄 Actualizando análisis de #{self.canal_info.nombre}...", ephemeral=True)
            
            # Analizar
            analisis = await self.analyzer.analizar_canal(channel)
            
            if 'error' in analisis:
                await interaction.followup.send(f"❌ {analisis['error']}", ephemeral=True)
                return
            
            # Crear nuevo embed y vista
            embed = self.bot.crear_embed_analisis(analisis)
            nueva_view = AnalisisView(self.bot, analisis, self.canal_info)
            
            # Actualizar el mensaje original
            await interaction.message.edit(embed=embed, view=nueva_view)
            
        except Exception as e:
            print(f"Error en ActualizarButton: {e}")
            import traceback
            traceback.print_exc()
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)

class AnalisisView(discord.ui.View):
    """Vista con botones para interactuar con el análisis"""
    
    def __init__(self, bot, analisis_data: Dict, canal_info: CanalInfo, timeout=300):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.analisis_data = analisis_data
        self.canal_info = canal_info
        
        # Agregar botones dinámicamente según el contenido
        self._crear_botones()
    
    def _crear_botones(self):
        """Crea botones según el contenido disponible"""
        # Botón para hilos si existen
        hilos = self.analisis_data.get('canales_relacionados', {}).get('hilos_activos', [])
        if hilos:
            # Crear dropdown para hilos
            self.add_item(HilosSelect(self.bot, hilos[:25], self.bot.analyzer))
        
        # Botón para más eventos si hay muchos
        if self.analisis_data.get('num_eventos', 0) > 5:
            self.add_item(VerMasEventosButton(self.canal_info, self.analisis_data))
        
        # Botón de actualizar
        self.add_item(ActualizarButton(self.bot, self.canal_info, self.bot.analyzer))
    
    async def on_timeout(self):
        """Cuando la vista expira, deshabilitamos todos los componentes"""
        for item in self.children:
            item.disabled = True
        
        # No podemos editar el mensaje aquí sin referencia, pero está bien
        # Los botones simplemente no funcionarán después del timeout

class CanalAnalyzer:
    """Analizador inteligente de canales Discord"""
    
    def __init__(self):
        self.canales_mapeados = {}  # {guild_id: {numero: CanalInfo}}
        self.canales_por_nombre = {}  # {guild_id: {nombre_normalizado: CanalInfo}}
        self.analisis_cache = {}    # {channel_id: analisis_data}
        self.client = openai.OpenAI(api_key=OPENAI_API_KEY)
    
    async def mapear_servidor(self, guild: discord.Guild, mensaje_status=None) -> Dict:
        """Mapea todos los canales disponibles del servidor con números"""
        print(f"📍 Mapeando canales de {guild.name}...")
        
        if mensaje_status:
            await mensaje_status.edit(content="🔍 **Paso 1/3**: Escaneando estructura del servidor...")
        
        canales = {}
        canales_por_nombre = {}
        numero = 1
        
        # Mapear canales de texto
        if mensaje_status:
            await mensaje_status.edit(content=f"📊 **Paso 2/3**: Identificando canales de texto... ({len(guild.text_channels)} encontrados)")
        
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).read_message_history:
                canal_info = CanalInfo(
                    id=channel.id,
                    nombre=channel.name,
                    numero=numero,
                    tipo='texto'
                )
                
                canales[numero] = canal_info
                
                # Guardar múltiples variaciones del nombre para búsqueda
                # 1. Nombre normalizado
                canales_por_nombre[canal_info.nombre_normalizado] = canal_info
                
                # 2. Nombre original en minúsculas
                canales_por_nombre[channel.name.lower()] = canal_info
                
                # 3. Nombre sin caracteres especiales
                nombre_sin_especiales = ''.join(c for c in channel.name.lower() if c.isalnum() or c.isspace())
                if nombre_sin_especiales and nombre_sin_especiales != channel.name.lower():
                    canales_por_nombre[nombre_sin_especiales] = canal_info
                
                # 4. Nombre con guiones reemplazados por espacios
                nombre_con_espacios = channel.name.lower().replace('-', ' ').replace('_', ' ')
                if nombre_con_espacios != channel.name.lower():
                    canales_por_nombre[nombre_con_espacios] = canal_info
                
                numero += 1
        
        # Mapear foros
        for forum in guild.forums:
            canal_info = CanalInfo(
                id=forum.id,
                nombre=forum.name,
                numero=numero,
                tipo='foro'
            )
            
            canales[numero] = canal_info
            canales_por_nombre[canal_info.nombre_normalizado] = canal_info
            canales_por_nombre[forum.name.lower()] = canal_info
            numero += 1
        
        # Mapear algunos hilos activos
        thread_count = 0
        for thread in guild.threads:
            if thread_count >= 20:  # Limitar para no saturar
                break
            if not thread.archived:
                canal_info = CanalInfo(
                    id=thread.id,
                    nombre=f"Hilo: {thread.name}",
                    numero=numero,
                    tipo='hilo'
                )
                
                canales[numero] = canal_info
                canales_por_nombre[canal_info.nombre_normalizado] = canal_info
                numero += 1
                thread_count += 1
        
        self.canales_mapeados[guild.id] = canales
        self.canales_por_nombre[guild.id] = canales_por_nombre
        
        if mensaje_status:
            await mensaje_status.edit(content=f"✅ **Paso 3/3**: ¡Mapeo completado! {len(canales)} canales identificados")
        
        print(f"✅ {len(canales)} canales mapeados")
        return canales
    
    def buscar_canal(self, guild_id: int, busqueda: str) -> Optional[CanalInfo]:
        """Busca un canal por número o nombre"""
        if guild_id not in self.canales_mapeados:
            return None
        
        print(f"🔎 Buscando canal: '{busqueda}'")
        
        # Intentar buscar por número primero
        try:
            numero = int(busqueda)
            canal = self.canales_mapeados[guild_id].get(numero)
            if canal:
                print(f"✅ Encontrado por número: {canal.nombre}")
                return canal
        except ValueError:
            pass
        
        # Buscar por nombre
        canales_por_nombre = self.canales_por_nombre.get(guild_id, {})
        
        # Normalizar búsqueda - eliminar espacios extra y guiones
        busqueda_normalizada = busqueda.lower().strip()
        busqueda_normalizada = busqueda_normalizada.replace('-', ' ').replace('_', ' ')
        
        # Búsqueda exacta primero
        for nombre_key, canal in canales_por_nombre.items():
            if busqueda_normalizada == nombre_key:
                print(f"✅ Encontrado exacto: {canal.nombre}")
                return canal
        
        # Búsqueda sin caracteres especiales
        busqueda_sin_especiales = ''.join(c for c in busqueda_normalizada if c.isalnum() or c.isspace())
        
        for nombre_key, canal in canales_por_nombre.items():
            nombre_sin_especiales = ''.join(c for c in nombre_key if c.isalnum() or c.isspace())
            
            # Comparar sin caracteres especiales
            if busqueda_sin_especiales == nombre_sin_especiales:
                print(f"✅ Encontrado sin especiales: {canal.nombre}")
                return canal
        
        # Búsqueda parcial - buscar que todas las palabras de la búsqueda estén en el nombre
        palabras_busqueda = busqueda_sin_especiales.split()
        
        for nombre_key, canal in canales_por_nombre.items():
            nombre_sin_especiales = ''.join(c for c in nombre_key if c.isalnum() or c.isspace())
            
            # Verificar que todas las palabras estén presentes
            if all(palabra in nombre_sin_especiales for palabra in palabras_busqueda):
                print(f"✅ Encontrado parcial: {canal.nombre}")
                return canal
        
        # Si no encontramos nada, buscar en los nombres originales de los canales
        for numero, canal in self.canales_mapeados[guild_id].items():
            nombre_original = canal.nombre.lower()
            if busqueda_normalizada in nombre_original or nombre_original in busqueda_normalizada:
                print(f"✅ Encontrado en nombre original: {canal.nombre}")
                return canal
        
        print(f"❌ No encontrado: '{busqueda}'")
        return None
    
    async def detectar_canales_relacionados(self, channel: discord.TextChannel) -> Dict:
        """Detecta foros e hilos relacionados con el canal"""
        relacionados = {
            'foros': [],
            'hilos_activos': [],
            'total': 0
        }
        
        # Buscar hilos en el canal
        try:
            for thread in channel.threads:
                if not thread.archived:
                    relacionados['hilos_activos'].append({
                        'nombre': thread.name,
                        'id': thread.id,
                        'mensajes': thread.message_count if hasattr(thread, 'message_count') else 0
                    })
            
            # También buscar en threads archivados recientes (opcional)
            async for thread in channel.archived_threads(limit=10):
                if (datetime.now() - thread.archive_timestamp).days < 30:  # Solo últimos 30 días
                    relacionados['hilos_activos'].append({
                        'nombre': f"{thread.name} (archivado)",
                        'id': thread.id,
                        'mensajes': thread.message_count if hasattr(thread, 'message_count') else 0
                    })
            
        except:
            pass  # Algunos canales no tienen hilos
        
        relacionados['total'] = len(relacionados['foros']) + len(relacionados['hilos_activos'])
        return relacionados
    
    async def analizar_canal(self, channel: discord.TextChannel, mensaje_status=None) -> Dict:
        """Analiza un canal con feedback detallado"""
        
        # Si ya está en caché, preguntar si re-analizar
        if channel.id in self.analisis_cache:
            cache_data = self.analisis_cache[channel.id]
            tiempo_cache = datetime.fromisoformat(cache_data['timestamp_analisis'])
            minutos_pasados = (datetime.now() - tiempo_cache).seconds // 60
            
            if minutos_pasados < 30:  # Cache válido por 30 minutos
                return cache_data
        
        print(f"🔍 Analizando canal #{channel.name}...")
        
        # Recolectar mensajes con feedback
        if mensaje_status:
            await mensaje_status.edit(content=f"📊 **Recolectando mensajes** de #{channel.name}...\n⏳ Esto puede tomar unos segundos...")
        
        mensajes = []
        mensajes_totales = 0
        autores_unicos = set()
        
        try:
            async for msg in channel.history(limit=2000):  # Aumentamos el límite
                mensajes_totales += 1
                
                # Incluir mensajes de usuarios Y algunos mensajes importantes de bots
                if msg.content and (not msg.author.bot or len(msg.content) > 100):
                    mensajes.append({
                        'id': msg.id,
                        'autor': msg.author.name,
                        'contenido': msg.content[:500],
                        'timestamp': msg.created_at,
                        'url': msg.jump_url,
                        'es_bot': msg.author.bot
                    })
                    autores_unicos.add(msg.author.name)
                
                # Actualizar progreso cada 100 mensajes
                if mensajes_totales % 100 == 0 and mensaje_status:
                    await mensaje_status.edit(
                        content=f"📊 **Recolectando mensajes** de #{channel.name}...\n"
                                f"📈 {mensajes_totales} mensajes revisados\n"
                                f"💬 {len(mensajes)} mensajes relevantes encontrados\n"
                                f"👥 {len(autores_unicos)} usuarios únicos"
                    )
        except discord.Forbidden:
            return {'error': 'No tengo permisos para leer este canal'}
        except Exception as e:
            return {'error': f'Error al leer canal: {str(e)}'}
        
        if not mensajes:
            return {'error': f'No se encontraron mensajes en este canal (revisados {mensajes_totales} mensajes totales)'}
        
        mensajes.reverse()  # Orden cronológico
        
        # Dividir en chunks para análisis
        chunk_size = 50
        chunks = [mensajes[i:i + chunk_size] for i in range(0, len(mensajes), chunk_size)]
        
        if mensaje_status:
            await mensaje_status.edit(
                content=f"🤖 **Analizando con IA** {len(mensajes)} mensajes...\n"
                        f"📊 Dividido en {len(chunks)} partes para análisis detallado\n"
                        f"⏳ Procesando..."
            )
        
        # Analizar cada chunk
        eventos = []
        resumen_general = ""
        temas_principales = []
        elementos_mundo = set()  # Para acumular elementos únicos del mundo
        
        for i, chunk in enumerate(chunks):
            if mensaje_status:
                porcentaje = int((i / len(chunks)) * 100)
                await mensaje_status.edit(
                    content=f"🤖 **Analizando con IA** - {porcentaje}%\n"
                            f"📍 Procesando parte {i+1}/{len(chunks)}...\n"
                            f"🔍 Detectando eventos y elementos del mundo"
                )
            
            analisis_chunk = await self._analizar_chunk_con_ia(chunk, channel.name, i+1, len(chunks))
            
            if analisis_chunk.get('eventos'):
                # Agregar referencia a mensajes específicos
                for evento in analisis_chunk['eventos']:
                    # Buscar mensaje relacionado y agregar metadatos
                    for msg in chunk:
                        if any(p in msg['autor'] for p in evento.get('participantes', [])):
                            evento['mensaje_url'] = msg['url']
                            evento['timestamp'] = msg['timestamp'].isoformat()
                            break
                
                eventos.extend(analisis_chunk['eventos'])
            
            # Acumular elementos del mundo
            if analisis_chunk.get('elementos_mundo'):
                elementos_mundo.update(analisis_chunk['elementos_mundo'])
            
            if i == 0:  # Primer chunk para resumen general
                resumen_general = analisis_chunk.get('resumen', '')
                temas_principales = analisis_chunk.get('temas', [])
        
        # Detectar canales relacionados (hilos, etc)
        canales_relacionados = await self.detectar_canales_relacionados(channel)
        
        # Consolidar análisis
        proposito_canal = ""
        for chunk_analisis in [a for a in [analisis_chunk] if a.get('proposito_canal')]:
            if chunk_analisis.get('proposito_canal'):
                proposito_canal = chunk_analisis['proposito_canal']
                break
        
        analisis_final = {
            'canal_nombre': channel.name,
            'canal_id': channel.id,
            'total_mensajes_revisados': mensajes_totales,
            'mensajes_analizados': len(mensajes),
            'usuarios_unicos': len(autores_unicos),
            'resumen_general': resumen_general,
            'proposito_canal': proposito_canal,
            'temas_principales': temas_principales,
            'elementos_mundo': list(elementos_mundo),  # Convertir set a lista
            'num_eventos': len(eventos),
            'eventos': sorted(eventos, key=lambda x: x.get('importancia', 'baja') == 'alta', reverse=True)[:15],
            'canales_relacionados': canales_relacionados,
            'timestamp_analisis': datetime.now().isoformat(),
            'mensaje_mas_antiguo': mensajes[0]['url'] if mensajes else None,
            'mensaje_mas_reciente': mensajes[-1]['url'] if mensajes else None
        }
        
        # Guardar en caché
        self.analisis_cache[channel.id] = analisis_final
        
        if mensaje_status:
            await mensaje_status.edit(content="✅ **¡Análisis completado!**")
        
        return analisis_final
    
    async def _analizar_chunk_con_ia(self, chunk: List[Dict], nombre_canal: str, parte: int, total_partes: int) -> Dict:
        """Analiza un chunk de mensajes con IA"""
        
        # Preparar mensajes filtrando bots si hay muchos
        mensajes_filtrados = [m for m in chunk if not m.get('es_bot')] or chunk
        
        mensajes_texto = "\n".join([
            f"[{msg['autor']}]: {msg['contenido']}"
            for msg in mensajes_filtrados[:40]  # Limitamos para no exceder tokens
        ])
        
        prompt = f"""
Analiza estos mensajes del canal #{nombre_canal} (Parte {parte}/{total_partes}).

CONTEXTO: Este es un servidor de roleplay/gaming. Los canales pueden ser:
- Lugares del mundo (ciudades, puertos, hospitales, etc.)
- Canales de información (reglas, guías, lore)
- Canales sociales (charla general, memes)
- Canales de personajes o facciones

MENSAJES:
{mensajes_texto}

INSTRUCCIONES CRÍTICAS:
1. Si es la parte 1, IDENTIFICA EL PROPÓSITO EXACTO:
   - Si es un LUGAR: ¿Qué lugar es? ¿Qué sucede ahí típicamente?
   - Si es INFORMACIÓN: ¿Sobre qué? (runas, marcas, reglas, guías)
   - Si es SOCIAL: ¿Qué tipo de interacciones?
   - Si es ROLEPLAY: ¿Qué historia o situación se desarrolla?

2. BUSCA ELEMENTOS ESPECÍFICOS DEL MUNDO:
   - Nombres de lugares (Puerto Bendito, Hospital Humano, etc.)
   - Objetos especiales (runas, marcas, artefactos)
   - Personajes o criaturas mencionadas
   - Sistemas del juego (niveles, habilidades, etc.)

3. EVENTOS - No generalices, sé ESPECÍFICO pero CONCISO:
   - En vez de "conversación general", di "discusión sobre las runas de esclavitud"
   - En vez de "roleplay", di "batalla entre X e Y en el puerto"
   - Mantén las descripciones bajo 60 caracteres
   - Incluye contexto del mundo siempre que sea posible

Responde en JSON:
{{
    "resumen": "descripción ESPECÍFICA: qué ES este canal y para QUÉ se usa",
    "temas": ["tema específico del mundo/servidor"],
    "proposito_canal": "roleplay/información/social/reglas/mercado/batalla/otro",
    "elementos_mundo": ["lugares/objetos/sistemas mencionados"],
    "eventos": [
        {{
            "tipo": "roleplay/información/conflicto/transacción/encuentro/otro",
            "descripcion": "descripción ESPECÍFICA con contexto del mundo",
            "participantes": ["usuario1", "usuario2"],
            "importancia": "alta/media/baja",
            "elementos_lore": ["elementos específicos mencionados"],
            "ubicacion": "lugar donde ocurre si se menciona",
            "cita_relevante": "frase exacta importante"
        }}
    ]
}}
"""
        
        try:
            # Hacer la llamada asíncrona con timeout
            import asyncio
            
            # Crear una tarea con timeout
            async def llamar_openai():
                loop = asyncio.get_event_loop()
                # Ejecutar en un thread separado para no bloquear
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.5,
                        max_tokens=800,
                        timeout=15  # Timeout de 15 segundos
                    )
                )
                return response
            
            try:
                response = await asyncio.wait_for(llamar_openai(), timeout=20)
                respuesta_texto = response.choices[0].message.content.strip()
            except asyncio.TimeoutError:
                print(f"⏱️ Timeout en análisis IA para {nombre_canal}")
                return {
                    "resumen": f"Análisis parcial de {nombre_canal}",
                    "temas": ["timeout"],
                    "eventos": [{
                        "tipo": "información",
                        "descripcion": "Análisis interrumpido por timeout",
                        "participantes": [],
                        "importancia": "baja"
                    }]
                }
            
            # Intentar parsear como JSON
            try:
                resultado = json.loads(respuesta_texto)
                # Asegurar que tiene la estructura esperada
                if 'eventos' not in resultado:
                    resultado['eventos'] = []
                return resultado
            except:
                # Si falla el parseo, crear estructura básica
                return {
                    "resumen": f"Actividad en {nombre_canal}",
                    "temas": [],
                    "eventos": [{
                        "tipo": "actividad",
                        "descripcion": "Actividad general del canal",
                        "participantes": list(set([msg['autor'] for msg in chunk[:5] if not msg.get('es_bot')])),
                        "importancia": "media"
                    }]
                }
                
        except Exception as e:
            print(f"❌ Error en análisis IA: {e}")
            return {"resumen": "", "temas": [], "eventos": []}

# ============= BOT PRINCIPAL =============

class ObserverBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )
        
        self.analyzer = CanalAnalyzer()
        self.servidores_activos = set()
    
    async def on_ready(self):
        print(f'✅ {self.user} está listo!')
        print(f'📊 Conectado a {len(self.guilds)} servidores')
        print(f'📌 Versión con botones interactivos activa')
        
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="menciones para analizar canales"
            )
        )
    
    async def on_message(self, message):
        # Ignorar mensajes propios y de bots
        if message.author.bot:
            return
        
        # Detectar menciones al bot
        if self.user in message.mentions:
            await self.procesar_comando_natural(message)
            return
        
        await self.process_commands(message)
    
    async def procesar_comando_natural(self, message: discord.Message):
        """Procesa comandos en lenguaje natural"""
        
        # Limpiar contenido
        contenido = message.content
        for mention in message.mentions:
            contenido = contenido.replace(f'<@{mention.id}>', '')
            contenido = contenido.replace(f'<@!{mention.id}>', '')
        contenido = contenido.strip()
        
        print(f"💬 Comando recibido de {message.author}: '{contenido}'")
        
        # Si no hay servidor activo, activar primero
        if message.guild.id not in self.servidores_activos:
            status_msg = await message.channel.send("🚀 **Activando Observer**... Mapeando canales del servidor...")
            await self.analyzer.mapear_servidor(message.guild, status_msg)
            self.servidores_activos.add(message.guild.id)
            await asyncio.sleep(1)
        
        # Detectar intención: analizar canal
        if any(palabra in contenido.lower() for palabra in ['analiza', 'analizar', 'mira', 'revisa', 'checa', 'canal']):
            await self.comando_analizar_canal(message, contenido)
        
        # Detectar intención: listar canales
        elif any(palabra in contenido.lower() for palabra in ['canales', 'lista', 'muestra', 'cuáles', 'todos']):
            await self.comando_listar_canales(message)
        
        # Ayuda por defecto
        else:
            await self.comando_ayuda(message)
    
    def crear_embed_analisis(self, analisis: Dict, es_hilo: bool = False) -> discord.Embed:
        """Crea un embed con los resultados del análisis"""
        
        # Título apropiado
        titulo = f"🧵 Análisis de Hilo: {analisis['canal_nombre']}" if es_hilo else f"📊 Análisis de #{analisis['canal_nombre']}"
        
        # Mejorar la descripción con el propósito del canal
        descripcion_canal = analisis['resumen_general'] or "Canal con actividad variada"
        if analisis.get('proposito_canal'):
            tipo_canal = {
                'roleplay': '🎭 Canal de Roleplay',
                'información': '📚 Canal Informativo', 
                'social': '💬 Canal Social',
                'reglas': '📜 Canal de Reglas',
                'otro': '📌 Canal Especial'
            }.get(analisis['proposito_canal'], '📌 Canal')
            descripcion_canal = f"**{tipo_canal}**\n{descripcion_canal}"
        
        # Limitar longitud de la descripción
        if len(descripcion_canal) > 2048:
            descripcion_canal = descripcion_canal[:2045] + "..."
        
        embed = discord.Embed(
            title=titulo,
            description=descripcion_canal,
            color=0x00ff00
        )
        
        # Estadísticas
        stats_text = f"• **Mensajes totales**: {analisis['total_mensajes_revisados']:,}\n"
        stats_text += f"• **Mensajes analizados**: {analisis['mensajes_analizados']:,}\n"
        stats_text += f"• **Usuarios únicos**: {analisis['usuarios_unicos']}\n"
        stats_text += f"• **Eventos detectados**: {analisis['num_eventos']}"
        
        # Agregar info de canales relacionados si existen
        if analisis.get('canales_relacionados') and analisis['canales_relacionados']['total'] > 0:
            stats_text += f"\n• **Hilos activos**: {len(analisis['canales_relacionados']['hilos_activos'])}"
        
        embed.add_field(
            name="📈 Estadísticas",
            value=stats_text,
            inline=True
        )
        
        # Enlaces rápidos
        embed.add_field(
            name="🔗 Enlaces Rápidos",
            value=f"• [Primer mensaje]({analisis['mensaje_mas_antiguo']})\n"
                  f"• [Último mensaje]({analisis['mensaje_mas_reciente']})",
            inline=True
        )
        
        # Temas principales y elementos del mundo
        if analisis.get('temas_principales') or analisis.get('elementos_mundo'):
            contenido_tematico = []
            
            if analisis.get('temas_principales'):
                temas = ', '.join(analisis['temas_principales'][:5])
                if len(temas) > 200:
                    temas = temas[:197] + "..."
                contenido_tematico.append(f'**Temas:** {temas}')
            
            if analisis.get('elementos_mundo'):
                elementos = ', '.join(analisis['elementos_mundo'][:7])
                if len(elementos) > 200:
                    elementos = elementos[:197] + "..."
                contenido_tematico.append(f'**Elementos del mundo:** {elementos}')
            
            if contenido_tematico:
                valor_campo = '\n'.join(contenido_tematico)
                # Verificación de longitud
                if len(valor_campo) > 1024:
                    valor_campo = valor_campo[:1020] + "..."
                
                embed.add_field(
                    name="📌 Contenido del Canal",
                    value=valor_campo,
                    inline=False
                )
        
        # Eventos importantes (primeros 5)
        if analisis['eventos']:
            eventos_texto = []
            caracteres_usados = 0
            max_caracteres = 900  # Dejamos margen para evitar el límite de 1024
            
            for i, evento in enumerate(analisis['eventos'][:10], 1):
                desc = evento['descripcion'][:50]  # Reducimos a 50 caracteres
                tipo = evento['tipo'].title()
                
                # Construir texto del evento
                if evento.get('mensaje_url'):
                    evento_str = f"**{i}. {tipo}**: [{desc}...]({evento['mensaje_url']})"
                else:
                    evento_str = f"**{i}. {tipo}**: {desc}..."
                
                # Agregar participantes solo si hay espacio
                if evento.get('participantes') and len(evento['participantes']) > 0:
                    participantes = ', '.join(evento['participantes'][:2])
                    evento_str += f"\n👥 *{participantes}*"
                
                # Verificar longitud antes de agregar
                if caracteres_usados + len(evento_str) + 20 < max_caracteres:
                    eventos_texto.append(evento_str)
                    caracteres_usados += len(evento_str) + 20
                else:
                    # Si no cabe más, indicar cuántos eventos más hay
                    eventos_restantes = analisis['num_eventos'] - i + 1
                    if eventos_restantes > 0:
                        eventos_texto.append(f"*...y {eventos_restantes} eventos más*")
                    break
            
            # Crear el campo solo si hay eventos
            if eventos_texto:
                valor_eventos = '\n\n'.join(eventos_texto)
                # Verificación final de longitud
                if len(valor_eventos) > 1024:
                    valor_eventos = valor_eventos[:1020] + "..."
                
                embed.add_field(
                    name="🎯 Eventos Destacados",
                    value=valor_eventos,
                    inline=False
                )
        
        embed.set_footer(text=f"Análisis realizado el {datetime.now().strftime('%Y-%m-%d %H:%M')} • Caché válido por 30 min")
        
        return embed
    
    async def comando_analizar_canal(self, message: discord.Message, contenido: str):
        """Analiza un canal específico"""
        
        # Extraer nombre/número del canal del mensaje
        # Primero intentar encontrar menciones de canal
        if message.channel_mentions:
            canal_mencionado = message.channel_mentions[0]
            # Buscar en nuestros canales mapeados
            for num, canal_info in self.analyzer.canales_mapeados.get(message.guild.id, {}).items():
                if canal_info.id == canal_mencionado.id:
                    busqueda = str(num)  # Usar el número
                    break
            else:
                busqueda = canal_mencionado.name
        else:
            # Limpiar el contenido de palabras clave
            palabras_clave = ['analiza', 'analizar', 'el', 'canal', 'mira', 'revisa', 'checa', '@observer']
            busqueda = contenido.lower()
            
            # Eliminar las palabras clave
            for palabra in palabras_clave:
                busqueda = busqueda.replace(palabra, ' ')
            
            # Limpiar espacios múltiples
            busqueda = ' '.join(busqueda.split()).strip()
        
        print(f"📝 Comando recibido: '{contenido}'")
        print(f"🔍 Búsqueda extraída: '{busqueda}'")
        
        if not busqueda:
            await message.channel.send(
                "❓ ¿Qué canal quieres que analice?\n\n"
                "**Ejemplos:**\n"
                "• `@Observer analiza canal 1`\n"
                "• `@Observer analiza el canal general`\n"
                "• `@Observer mira el canal memes`"
            )
            return
        
        # Buscar canal
        canal_info = self.analyzer.buscar_canal(message.guild.id, busqueda)
        
        if not canal_info:
            # Intentar búsqueda más flexible
            print(f"❌ Primera búsqueda falló, intentando búsqueda flexible...")
            
            # Mostrar lista de canales disponibles
            canales = self.analyzer.canales_mapeados.get(message.guild.id, {})
            
            embed = discord.Embed(
                title="❌ Canal no encontrado",
                description=f"No encontré un canal llamado **'{busqueda}'**",
                color=0xff0000
            )
            
            # Buscar canales similares
            sugerencias = []
            busqueda_palabras = busqueda.lower().split()
            
            for num, canal in canales.items():
                nombre_lower = canal.nombre.lower()
                # Si alguna palabra de la búsqueda está en el nombre
                if any(palabra in nombre_lower for palabra in busqueda_palabras if len(palabra) > 2):
                    sugerencias.append(f"**{num}.** {canal.nombre}")
                    
                if len(sugerencias) >= 10:
                    break
            
            if sugerencias:
                embed.add_field(
                    name="📋 ¿Quizás quisiste decir?",
                    value='\n'.join(sugerencias),
                    inline=False
                )
            else:
                # Mostrar primeros 10 canales
                primeros_10 = []
                for num, canal in list(canales.items())[:10]:
                    primeros_10.append(f"**{num}.** {canal.nombre}")
                
                embed.add_field(
                    name="📋 Algunos canales disponibles:",
                    value='\n'.join(primeros_10),
                    inline=False
                )
            
            embed.add_field(
                name="💡 Usa el número o nombre completo:",
                value="`@Observer analiza canal 1` o `@Observer analiza bosque oscuro`",
                inline=False
            )
            
            await message.channel.send(embed=embed)
            return
        
        # Obtener el canal
        channel = message.guild.get_channel(canal_info.id)
        if not channel:
            await message.channel.send("❌ No puedo acceder a ese canal.")
            return
        
        # Mensaje de estado
        status_msg = await message.channel.send(f"🔍 **Iniciando análisis** de #{canal_info.nombre}...")
        
        # Analizar canal
        try:
            analisis = await self.analyzer.analizar_canal(channel, status_msg)
            
            if 'error' in analisis:
                await status_msg.edit(content=f"❌ {analisis['error']}")
                return
            
            # Crear embed con resultados
            embed = self.crear_embed_analisis(analisis)
            
            # Crear vista con botones interactivos
            view = AnalisisView(self, analisis, canal_info)
            
            # Actualizar mensaje con embed y vista
            await status_msg.edit(content=None, embed=embed, view=view)
            
        except Exception as e:
            await status_msg.edit(content=f"❌ Error al analizar: {str(e)}")
            print(f"Error en análisis: {e}")
            import traceback
            traceback.print_exc()
    
    async def comando_listar_canales(self, message: discord.Message):
        """Lista TODOS los canales disponibles"""
        
        if message.guild.id not in self.analyzer.canales_mapeados:
            await message.channel.send("❌ Primero necesito mapear el servidor. Mencióname para activarme.")
            return
        
        canales = self.analyzer.canales_mapeados[message.guild.id]
        
        # Crear múltiples embeds si hay muchos canales
        canales_por_embed = 20
        total_embeds = (len(canales) + canales_por_embed - 1) // canales_por_embed
        
        for embed_num in range(total_embeds):
            inicio = embed_num * canales_por_embed
            fin = min(inicio + canales_por_embed, len(canales))
            
            embed = discord.Embed(
                title=f"📋 Lista Completa de Canales ({embed_num + 1}/{total_embeds})",
                description=f"**Total: {len(canales)} canales** - Usa el número o nombre para analizar",
                color=0x00ff00
            )
            
            # Dividir en columnas
            canales_texto = []
            for num in range(inicio + 1, fin + 1):
                if num in canales:
                    canal = canales[num]
                    tipo_icon = "💬" if canal.tipo == "texto" else "📂" if canal.tipo == "foro" else "🧵"
                    canales_texto.append(f"{tipo_icon} **{num}.** {canal.nombre}")
            
            # Dividir en dos columnas si hay muchos
            if len(canales_texto) > 10:
                mitad = len(canales_texto) // 2
                embed.add_field(
                    name=f"Canales {inicio + 1}-{inicio + mitad}",
                    value='\n'.join(canales_texto[:mitad]),
                    inline=True
                )
                embed.add_field(
                    name=f"Canales {inicio + mitad + 1}-{fin}",
                    value='\n'.join(canales_texto[mitad:]),
                    inline=True
                )
            else:
                embed.add_field(
                    name=f"Canales {inicio + 1}-{fin}",
                    value='\n'.join(canales_texto),
                    inline=False
                )
            
            if embed_num == 0:
                embed.add_field(
                    name="💡 Cómo usar",
                    value="• `@Observer analiza canal 5` (por número)\n• `@Observer analiza general` (por nombre)",
                    inline=False
                )
            
            await message.channel.send(embed=embed)
            
            # Pausa entre embeds para evitar rate limit
            if embed_num < total_embeds - 1:
                await asyncio.sleep(0.5)
    
    async def comando_ayuda(self, message: discord.Message):
        """Muestra ayuda del bot"""
        
        embed = discord.Embed(
            title="🔍 Observer - Análisis Inteligente de Discord",
            description="Analizo canales y encuentro información importante usando IA.",
            color=0x00ff00
        )
        
        embed.add_field(
            name="📌 Comandos Principales",
            value="• `@Observer analiza canal [número/nombre]`\n"
                  "• `@Observer lista todos los canales`\n"
                  "• `@Observer ayuda`",
            inline=False
        )
        
        embed.add_field(
            name="💡 Ejemplos de Uso",
            value="• `@Observer analiza canal 1`\n"
                  "• `@Observer analiza el canal general`\n"
                  "• `@Observer mira memes`\n"
                  "• `@Observer revisa el canal de anuncios`",
            inline=False
        )
        
        embed.add_field(
            name="🎯 Qué puedo hacer",
            value="• Analizo conversaciones y detecto eventos importantes\n"
                  "• Identifico temas principales de cada canal\n"
                  "• Proporciono links directos a mensajes relevantes\n"
                  "• Resumo la actividad del canal de forma clara\n"
                  "• Detecto participantes activos y momentos destacados",
            inline=False
        )
        
        embed.add_field(
            name="✨ Funciones Interactivas",
            value="• **Botones en resultados** para navegar fácilmente\n"
                  "• **Analizar hilos** directamente desde el análisis\n"
                  "• **Ver más eventos** con un click\n"
                  "• **Actualizar análisis** cuando lo necesites",
            inline=False
        )
        
        embed.add_field(
            name="⚡ Tips",
            value="• Puedo buscar por **número** de canal o por **nombre**\n"
                  "• Los análisis se guardan en caché por 30 minutos\n"
                  "• Incluyo links directos a eventos importantes\n"
                  "• Proceso hasta 2000 mensajes por canal",
            inline=False
        )
        
        embed.set_footer(text="💡 Solo mencióname y dime qué canal quieres que analice")
        
        await message.channel.send(embed=embed)

# ============= INICIAR BOT =============

if __name__ == "__main__":
    bot = ObserverBot()
    bot.run(DISCORD_TOKEN)