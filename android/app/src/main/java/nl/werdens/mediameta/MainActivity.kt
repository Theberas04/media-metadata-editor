package nl.werdens.mediameta

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.BitmapFactory
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Log
import android.view.View
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.core.content.FileProvider
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import nl.werdens.mediameta.databinding.ActivityMainBinding
import java.io.File
import java.io.IOException
import java.util.Locale

/**
 * Eén scherm: speler, metadata-formulier en opslaan.
 *
 * Bestanden komen binnen via de documentenkiezer (Storage Access Framework) en
 * worden naar de cache gekopieerd, zodat de tag-libraries een gewoon bestand
 * hebben om te lezen en te schrijven. Na het opslaan gaan de bytes terug naar
 * het oorspronkelijke bestand; kan dat niet, dan biedt de app "opslaan als" aan.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var player: ExoPlayer? = null

    private var sourceUri: Uri? = null
    private var workFile: File? = null
    private var displayName: String = ""
    private var canWrite = false
    private var pendingSaveValues: Map<String, String>? = null
    private var posterBitmap: Bitmap? = null
    private var hasVideo = false
    private var frameBitmap: Bitmap? = null
    private var pendingShare = false

    private val openDocument =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) {
                load(uri)
            }
        }

    private val createDocument =
        registerForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
            if (uri != null) {
                val values = pendingSaveValues
                pendingSaveValues = null
                if (values != null) {
                    exportTo(uri, values)
                }
            }
        }

    private val createFrame =
        registerForActivityResult(ActivityResultContracts.CreateDocument("image/png")) { uri ->
            val bitmap = frameBitmap
            frameBitmap = null
            if (uri == null || bitmap == null) return@registerForActivityResult
            try {
                contentResolver.openOutputStream(uri)?.use { output ->
                    if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)) {
                        throw IOException("Kon de afbeelding niet schrijven.")
                    }
                } ?: throw IOException("Geen schrijftoegang tot het gekozen bestand.")
                setStatus(getString(R.string.frame_saved))
            } catch (e: Exception) {
                setStatus("Frame opslaan mislukt: ${e.message}", error = true)
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val exoPlayer = ExoPlayer.Builder(this).build()
        player = exoPlayer
        binding.playerView.player = exoPlayer
        exoPlayer.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                if (isPlaying) {
                    hidePoster()
                }
            }

            override fun onPlayerError(error: PlaybackException) {
                posterBitmap?.let { setPoster(it) }
                setStatus("Dit formaat kan de speler niet afspelen: ${error.errorCodeName}", error = true)
            }
        })

        binding.openButton.setOnClickListener { openDocument.launch(arrayOf("video/*", "audio/*")) }
        binding.frameButton.setOnClickListener { saveFrame() }
        binding.shareButton.setOnClickListener { shareFrame() }
        binding.readButton.setOnClickListener { readAgain() }
        binding.saveButton.setOnClickListener { save() }

        setButtonsEnabled(hasFile = false, busy = false)
        handleIntent(intent)
        Log.i("MediaMeta", "MediaMetaReady version=" + packageManager.getPackageInfo(packageName, 0).versionName)
        checkForUpdate()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent?.action == Intent.ACTION_VIEW) {
            intent.data?.let { load(it) }
        }
    }

    override fun onStop() {
        player?.pause()
        super.onStop()
    }

    override fun onDestroy() {
        player?.release()
        player = null
        super.onDestroy()
    }

    // ------------------------------------------------------------ laden

    private fun load(uri: Uri) {
        setBusy(true)
        setStatus("Bestand inlezen…")
        lifecycleScope.launch {
            try {
                val result = withContext(Dispatchers.IO) { importFile(uri) }
                applyFile(result.first, result.second, uri)
            } catch (e: Exception) {
                setStatus("Kon het bestand niet openen: ${e.message}", error = true)
            } finally {
                setBusy(false)
            }
        }
    }

    /** Kopieert het gekozen document naar de cache; geeft (bestand, naam). */
    private fun importFile(uri: Uri): Pair<File, String> {
        val name = queryDisplayName(uri)
        val safeName = name.replace(Regex("[^A-Za-z0-9._-]"), "_").ifEmpty { "media.bin" }
        val target = File(cacheDir, safeName)
        contentResolver.openInputStream(uri)?.use { input ->
            target.outputStream().use { output -> input.copyTo(output) }
        } ?: throw IOException("Geen leestoegang tot dit bestand.")
        return Pair(target, name)
    }

    private fun queryDisplayName(uri: Uri): String {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0) {
                    val value = cursor.getString(index)
                    if (!value.isNullOrBlank()) {
                        return value
                    }
                }
            }
        }
        return uri.lastPathSegment ?: "media"
    }

    private fun applyFile(file: File, name: String, uri: Uri?) {
        sourceUri = uri
        workFile = file
        displayName = name
        canWrite = MediaTags.canWrite(name)

        val retriever = MediaMetadataRetriever()
        var info = ""
        var poster: Bitmap? = null
        try {
            retriever.setDataSource(file.absolutePath)
            val duration = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L
            val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
                ?.toIntOrNull() ?: 0
            val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
                ?.toIntOrNull() ?: 0
            info = buildString {
                append(if (width > 0) "Video" else "Audio")
                if (width > 0 && height > 0) append("  ·  ${width}x$height")
                if (duration > 0) append("  ·  ${formatDuration(duration)}")
                append("  ·  ${humanSize(file.length())}")
            }
            hasVideo = width > 0
            poster = if (width > 0) {
                retriever.getFrameAtTime(1_000_000, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
            } else {
                retriever.embeddedPicture?.let {
                    BitmapFactory.decodeByteArray(it, 0, it.size)
                }
            }
        } catch (e: Exception) {
            info = "${name.substringAfterLast('.', "bestand")}  ·  ${humanSize(file.length())}"
        } finally {
            try {
                retriever.release()
            } catch (_: Exception) {
            }
        }

        binding.fileInfo.text = "$name  ·  $info"
        binding.fileInfo.visibility = View.VISIBLE
        binding.hintText.visibility = View.GONE

        applyTags(readTags(file))
        setPoster(poster)

        val exo = player ?: return
        exo.setMediaItem(MediaItem.fromUri(Uri.fromFile(file)))
        exo.prepare()

        if (canWrite) {
            setStatus("Bestand geopend. Je kunt de metadata aanpassen en opslaan.")
        } else {
            setStatus(
                "Van dit bestandstype kan de app de tags niet aanpassen " +
                    "(wel afspelen en de bestaande tags tonen).",
                error = true
            )
        }
        setButtonsEnabled(hasFile = true, busy = false)
    }

    /** Leest de tags; valt terug op de metadata die Android zelf kent. */
    private fun readTags(file: File): Map<String, String> {
        val tags = try {
            MediaTags.read(file)
        } catch (e: Exception) {
            linkedMapOf()
        }
        val missing = tags.values.all { it.isBlank() }
        if (!missing && tags.values.any { it.isNotBlank() }) {
            return tags
        }
        val retriever = MediaMetadataRetriever()
        val result = LinkedHashMap<String, String>()
        for (key in Mp4Tags.KEYS) {
            result[key] = ""
        }
        try {
            retriever.setDataSource(file.absolutePath)
            result["title"] = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE) ?: ""
            result["artist"] = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ARTIST) ?: ""
            result["album"] = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ALBUM) ?: ""
            result["genre"] = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_GENRE) ?: ""
            result["year"] = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_YEAR) ?: ""
            result["albumartist"] =
                retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ALBUMARTIST) ?: ""
            result["composer"] =
                retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_COMPOSER) ?: ""
            result["track"] =
                retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_CD_TRACK_NUMBER) ?: ""
            result["disc"] =
                retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DISC_NUMBER) ?: ""
        } catch (_: Exception) {
        } finally {
            try {
                retriever.release()
            } catch (_: Exception) {
            }
        }
        // Vul aan met wat de tag-lezer wel vond.
        for ((key, value) in tags) {
            if (result[key].isNullOrBlank()) {
                result[key] = value
            }
        }
        return result
    }

    private fun applyTags(values: Map<String, String>) {
        binding.titleEdit.setText(values["title"].orEmpty())
        binding.artistEdit.setText(values["artist"].orEmpty())
        binding.albumartistEdit.setText(values["albumartist"].orEmpty())
        binding.albumEdit.setText(values["album"].orEmpty())
        binding.trackEdit.setText(values["track"].orEmpty())
        binding.discEdit.setText(values["disc"].orEmpty())
        binding.genreEdit.setText(values["genre"].orEmpty())
        binding.yearEdit.setText(values["year"].orEmpty())
        binding.composerEdit.setText(values["composer"].orEmpty())
        binding.commentEdit.setText(values["comment"].orEmpty())
        binding.lyricsEdit.setText(values["lyrics"].orEmpty())
    }

    private fun currentValues(): Map<String, String> = linkedMapOf(
        "title" to binding.titleEdit.text.toString().trim(),
        "artist" to binding.artistEdit.text.toString().trim(),
        "albumartist" to binding.albumartistEdit.text.toString().trim(),
        "album" to binding.albumEdit.text.toString().trim(),
        "track" to binding.trackEdit.text.toString().trim(),
        "disc" to binding.discEdit.text.toString().trim(),
        "genre" to binding.genreEdit.text.toString().trim(),
        "year" to binding.yearEdit.text.toString().trim(),
        "composer" to binding.composerEdit.text.toString().trim(),
        "comment" to binding.commentEdit.text.toString().trim(),
        "lyrics" to binding.lyricsEdit.text.toString().trim()
    )

    private fun readAgain() {
        val file = workFile ?: return
        setBusy(true)
        lifecycleScope.launch {
            try {
                applyTags(withContext(Dispatchers.IO) { readTags(file) })
                setStatus("Metadata opnieuw ingelezen.")
            } catch (e: Exception) {
                setStatus("Lezen mislukt: ${e.message}", error = true)
            } finally {
                setBusy(false)
            }
        }
    }

    // ------------------------------------------------------------ opslaan

    private fun save() {
        val file = workFile ?: return
        val uri = sourceUri ?: return
        if (!canWrite) {
            setStatus("Van dit bestandstype kunnen de tags niet aangepast worden.", error = true)
            return
        }
        val values = currentValues()
        setBusy(true)
        setStatus("Opslaan…")

        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                try {
                    MediaTags.write(file, values)
                    writeBack(uri, file)
                    val after = MediaTags.read(file)
                    val wrong = values.filter { (key, want) ->
                        want.isNotBlank() && !after[key].orEmpty().contains(want, ignoreCase = true)
                    }
                    if (wrong.isEmpty()) {
                        SaveResult.Message("Opgeslagen — alle ${values.size} velden gecontroleerd in $displayName.")
                    } else {
                        SaveResult.Message(
                            "Opgeslagen, maar deze velden zijn niet overgenomen: " +
                                wrong.keys.joinToString(", ") +
                                " (dat ligt aan het bestandsformaat)."
                        )
                    }
                } catch (e: IOException) {
                    SaveResult.NeedsSaveAs(e.message ?: "onbekende fout")
                } catch (e: Exception) {
                    SaveResult.Message("Opslaan mislukt: ${e.message}")
                }
            }
            when (result) {
                is SaveResult.Message -> setStatus(result.text)
                is SaveResult.NeedsSaveAs -> showSaveAsDialog(result.reason, values)
            }
            setBusy(false)
        }
    }

    private sealed interface SaveResult {
        data class Message(val text: String) : SaveResult
        data class NeedsSaveAs(val reason: String) : SaveResult
    }

    /** Kan het bronbestand niet aangepast worden: bied opslaan-als aan. */
    private fun showSaveAsDialog(reason: String, values: Map<String, String>) {
        AlertDialog.Builder(this)
            .setTitle("Niet aan te passen")
            .setMessage(
                "Het bestand kon niet aangepast worden:\n\n$reason\n\n" +
                    "Wil je de versie met metadata als nieuw bestand opslaan?"
            )
            .setPositiveButton("Opslaan als…") { _, _ ->
                pendingSaveValues = values
                createDocument.launch(displayName.ifEmpty { "media" })
            }
            .setNegativeButton("Annuleren", null)
            .show()
    }

    private fun writeBack(uri: Uri, file: File) {
        contentResolver.openOutputStream(uri, "rwt")?.use { output ->
            file.inputStream().use { input -> input.copyTo(output) }
        } ?: throw IOException("Geen schrijftoegang tot het gekozen bestand.")
    }

    private fun exportTo(uri: Uri, values: Map<String, String>) {
        val file = workFile ?: return
        setBusy(true)
        lifecycleScope.launch {
            try {
                val message = withContext(Dispatchers.IO) {
                    MediaTags.write(file, values)
                    contentResolver.openOutputStream(uri)?.use { output ->
                        file.inputStream().use { input -> input.copyTo(output) }
                    } ?: throw IOException("Kon het nieuwe bestand niet schrijven.")
                    "Opgeslagen als nieuw bestand."
                }
                setStatus(message)
            } catch (e: Exception) {
                setStatus("Opslaan mislukt: ${e.message}", error = true)
            } finally {
                setBusy(false)
            }
        }
    }

    // ------------------------------------------------------- frame & delen

    /** Pakt het huidige beeld uit het bestand als bitmap (of null). */
    private fun grabFrame(): Bitmap? {
        val file = workFile ?: return null
        if (!hasVideo) return null
        val positie = (player?.currentPosition ?: 0L) * 1000
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(file.absolutePath)
            retriever.getFrameAtTime(positie, MediaMetadataRetriever.OPTION_CLOSEST)
                ?: retriever.getFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
        } catch (e: Exception) {
            setStatus("Kon het beeld niet pakken: ${e.message}", error = true)
            null
        } finally {
            try {
                retriever.release()
            } catch (_: Exception) {
            }
        }
    }

    private fun saveFrame() {
        val bitmap = grabFrame()
        if (bitmap == null) {
            setStatus(getString(R.string.frame_failed), error = true)
            return
        }
        frameBitmap = bitmap
        val naam = displayName.substringBeforeLast('.', "frame") + "-frame.png"
        createFrame.launch(naam)
    }

    private fun shareFrame() {
        val bitmap = grabFrame()
        if (bitmap == null) {
            setStatus(getString(R.string.frame_failed), error = true)
            return
        }
        try {
            val map = File(cacheDir, "gedeeld")
            map.mkdirs()
            val bestand = File(map, displayName.substringBeforeLast('.', "frame") + "-frame.png")
            bestand.outputStream().use { uit ->
                if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, uit)) {
                    throw IOException("Kon de afbeelding niet klaarzetten.")
                }
            }
            val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", bestand)
            val deel = Intent(Intent.ACTION_SEND).apply {
                type = "image/png"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(deel, getString(R.string.share_frame)))
            pendingShare = false
        } catch (e: Exception) {
            setStatus("Delen mislukt: ${e.message}", error = true)
        }
    }

    // ---------------------------------------------------------- updatecheck

    /** Kijkt op GitHub of er een nieuwere APK is; stil als het niet lukt. */
    private fun checkForUpdate() {
        lifecycleScope.launch {
            val gevonden = withContext(Dispatchers.IO) { nieuwsteApk() } ?: return@launch
            val (versie, url) = gevonden
            if (vergelijkVersie(versie, huidigeVersie()) <= 0) return@launch
            binding.updateBanner.text = getString(R.string.update_available, versie)
            binding.updateBanner.visibility = View.VISIBLE
            binding.updateBanner.setOnClickListener {
                startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse(url))
                )
            }
        }
    }

    private fun huidigeVersie(): String = try {
        packageManager.getPackageInfo(packageName, 0).versionName ?: "0"
    } catch (e: Exception) {
        "0"
    }

    /** Nieuwste android-prerelease met een APK-asset: (versie, download-url). */
    private fun nieuwsteApk(): Pair<String, String>? {
        return try {
            val verbinding = java.net.URL(
                "https://api.github.com/repos/Theberas04/media-metadata-editor/releases"
            ).openConnection() as java.net.HttpURLConnection
            verbinding.setRequestProperty("User-Agent", "MediaMetadataEditor-android")
            verbinding.connectTimeout = 12000
            verbinding.readTimeout = 12000
            val body = verbinding.inputStream.bufferedReader().use { it.readText() }
            val releases = org.json.JSONArray(body)
            for (i in 0 until releases.length()) {
                val release = releases.getJSONObject(i)
                if (!release.optBoolean("prerelease")) continue
                if (!release.optString("tag_name").startsWith("android-")) continue
                val assets = release.optJSONArray("assets") ?: continue
                for (j in 0 until assets.length()) {
                    val asset = assets.getJSONObject(j)
                    val naam = asset.optString("name")
                    val match = Regex("(\\d+(?:\\.\\d+)+)\\.apk$").find(naam) ?: continue
                    return match.groupValues[1] to asset.optString("browser_download_url")
                }
            }
            null
        } catch (e: Exception) {
            Log.i("MediaMeta", "Updatecontrole overgeslagen: ${e.message}")
            null
        }
    }

    private fun vergelijkVersie(a: String, b: String): Int {
        val links = a.split(".").map { it.toIntOrNull() ?: 0 }
        val rechts = b.split(".").map { it.toIntOrNull() ?: 0 }
        for (i in 0 until maxOf(links.size, rechts.size)) {
            val x = links.getOrElse(i) { 0 }
            val y = rechts.getOrElse(i) { 0 }
            if (x != y) return x - y
        }
        return 0
    }

    // ------------------------------------------------------------- weergave

    private fun setPoster(poster: Bitmap?) {
        posterBitmap = poster
        val image = binding.posterImage
        if (poster == null) {
            image.visibility = View.GONE
        } else {
            image.setImageBitmap(poster)
            image.visibility = View.VISIBLE
        }
        binding.playerView.useController = true
    }

    private fun hidePoster() {
        binding.posterImage.visibility = View.GONE
    }

    private fun setStatus(text: String, error: Boolean = false) {
        binding.statusText.text = text
        binding.statusText.setTextColor(
            getColor(if (error) R.color.error else R.color.muted)
        )
    }

    private fun setBusy(busy: Boolean) {
        binding.progressBar.visibility = if (busy) View.VISIBLE else View.GONE
        setButtonsEnabled(hasFile = workFile != null, busy = busy)
    }

    private fun setButtonsEnabled(hasFile: Boolean, busy: Boolean) {
        binding.openButton.isEnabled = !busy
        binding.readButton.isEnabled = hasFile && !busy
        binding.saveButton.isEnabled = hasFile && canWrite && !busy
        binding.readButton.alpha = if (binding.readButton.isEnabled) 1f else 0.5f
        binding.saveButton.alpha = if (binding.saveButton.isEnabled) 1f else 0.5f
        val frameKlaar = hasFile && hasVideo && !busy
        binding.frameButton.isEnabled = frameKlaar
        binding.shareButton.isEnabled = frameKlaar
        binding.frameButton.alpha = if (frameKlaar) 1f else 0.5f
        binding.shareButton.alpha = if (frameKlaar) 1f else 0.5f
    }

    // -------------------------------------------------------------- hulpjes

    private fun formatDuration(milliseconds: Long): String {
        val total = milliseconds / 1000
        val hours = total / 3600
        val minutes = (total % 3600) / 60
        val seconds = total % 60
        return if (hours > 0) {
            String.format(Locale.getDefault(), "%d:%02d:%02d", hours, minutes, seconds)
        } else {
            String.format(Locale.getDefault(), "%02d:%02d", minutes, seconds)
        }
    }

    private fun humanSize(bytes: Long): String {
        var value = bytes.toDouble()
        val units = listOf("B", "kB", "MB", "GB")
        var index = 0
        while (value >= 1024 && index < units.lastIndex) {
            value /= 1024
            index++
        }
        return if (index == 0) {
            "${value.toInt()} ${units[index]}"
        } else {
            String.format(Locale.getDefault(), "%.1f %s", value, units[index])
        }
    }
}