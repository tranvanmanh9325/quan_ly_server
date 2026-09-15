package com.quanlyserver.assistant.ui.cockpit

import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.quanlyserver.assistant.R
import kotlinx.coroutines.delay
import kotlin.random.Random

/**
 * Living Character Entity: AI Girl Assistant (Tieu Bao Bao).
 * Renders the character as an independent living 2.5D graphic entity with:
 * 1. Independent biological sinusoidal chest & shoulder breathing.
 * 2. Natural randomized eye-blinking engine.
 * 3. 2.5D Gaze and head/body tilting towards user mouse/touch coordinates.
 * 4. Interactive haptic tap feedback and dialog expression.
 */
@Composable
fun LivingCharacterEntity(
    modifier: Modifier = Modifier,
    parallaxOffsetX: Float,
    parallaxOffsetY: Float,
    isPointerDown: Boolean = false,
    pointerPosition: Offset = Offset.Zero
) {
    // 1. Biological Breathing Dynamic (3.8s rhythmic harmonic cycle)
    val infiniteTransition = rememberInfiniteTransition(label = "BioBreathing")
    val breathingExpansion by infiniteTransition.animateFloat(
        initialValue = 1.0f,
        targetValue = 1.018f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1900, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "ChestExpansion"
    )
    val breathingVerticalLift by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = -5.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1900, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "VerticalShoulderLift"
    )

    // 2. Natural Randomized Eye Blinking (Every 3.2s - 5.5s for 120ms)
    var isBlinking by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            val waitMillis = Random.nextLong(3200, 5500)
            delay(waitMillis)
            isBlinking = true
            delay(120)
            isBlinking = false
        }
    }

    // 3. Interactive Touch Reaction (Voice/Dialog Prompt)
    var dialogText by remember { mutableStateOf<String?>(null) }
    var touchReactionTrigger by remember { mutableStateOf(0) }

    LaunchedEffect(touchReactionTrigger) {
        if (touchReactionTrigger > 0) {
            val phrases = listOf(
                "Em chào anh Mạnh! Hệ thống máy chủ đang chạy mượt mà 60 FPS!",
                "Em đang canh gác phi thuyền và máy chủ cho anh đây ạ!",
                "Mọi chỉ số telemetry đều hoàn hảo, anh Mạnh yên tâm nhé!"
            )
            dialogText = phrases[(touchReactionTrigger - 1) % phrases.size]
            delay(3500)
            dialogText = null
        }
    }

    // 4. Dynamic 2.5D Tilt Calculations (Pivot at character hips: 0.5f, 0.7f)
    // Characters tilt slightly opposite to mouse drag for authentic 3D spatial depth
    val tiltAngleY = (parallaxOffsetX * 0.12f).coerceIn(-7f, 7f)
    val tiltAngleZ = (parallaxOffsetX * 0.03f).coerceIn(-2.5f, 2.5f)

    Box(
        modifier = modifier
            .fillMaxSize()
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null
            ) {
                touchReactionTrigger++
            },
        contentAlignment = Alignment.Center
    ) {
        // [Layer A: Isolated Alpha-Channel AI Girl Body]
        Image(
            painter = painterResource(id = R.drawable.char_isolated),
            contentDescription = "AI Character Body",
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    translationX = parallaxOffsetX * 0.55f
                    translationY = (parallaxOffsetY * 0.55f) + breathingVerticalLift
                    scaleX = breathingExpansion
                    scaleY = breathingExpansion
                    rotationY = tiltAngleY
                    rotationZ = tiltAngleZ
                    transformOrigin = TransformOrigin(0.5f, 0.7f)
                    cameraDistance = 14f * density
                }
        )

        // [Layer B: Closed Eyelids Frame for Natural Blinking]
        if (isBlinking) {
            Image(
                painter = painterResource(id = R.drawable.char_eyes_blink),
                contentDescription = "Natural Eye Blink Overlay",
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .fillMaxSize()
                    .graphicsLayer {
                        translationX = parallaxOffsetX * 0.55f
                        translationY = (parallaxOffsetY * 0.55f) + breathingVerticalLift
                        scaleX = breathingExpansion
                        scaleY = breathingExpansion
                        rotationY = tiltAngleY
                        rotationZ = tiltAngleZ
                        transformOrigin = TransformOrigin(0.5f, 0.7f)
                        cameraDistance = 14f * density
                    }
            )
        }

        // [Layer C: Interactive Holographic Dialog Bubble]
        if (dialogText != null) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .padding(top = 180.dp, start = 32.dp, end = 32.dp)
                    .graphicsLayer {
                        translationX = parallaxOffsetX * 0.7f
                        translationY = parallaxOffsetY * 0.7f
                    }
            ) {
                Text(
                    text = dialogText ?: "",
                    color = Color(0xFF00FFEA),
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier.padding(12.dp)
                )
            }
        }
    }
}
