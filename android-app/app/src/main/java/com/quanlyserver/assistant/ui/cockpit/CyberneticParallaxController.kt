package com.quanlyserver.assistant.ui.cockpit

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.max
import kotlin.math.min

data class ParallaxOffset(val roll: Float = 0f, val pitch: Float = 0f)

/**
 * Smooth Gyroscope & Touch Sensor Fusion Engine.
 * Provides micro-parallax perspective shifts using Exponential Moving Average (EMA) filtering.
 */
class CyberneticParallaxController(context: Context) : SensorEventListener {
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
    private val rotationSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)

    private val _offsetFlow = MutableStateFlow(ParallaxOffset())
    val offsetFlow: StateFlow<ParallaxOffset> = _offsetFlow.asStateFlow()

    private val smoothing = 0.08f
    private var currentRoll = 0f
    private var currentPitch = 0f

    fun start() {
        rotationSensor?.let {
            sensorManager?.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME)
        }
    }

    fun stop() {
        sensorManager?.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent?) {
        if (event == null || event.sensor.type != Sensor.TYPE_ROTATION_VECTOR) return

        val rotationMatrix = FloatArray(9)
        val orientation = FloatArray(3)
        SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
        SensorManager.getOrientation(rotationMatrix, orientation)

        val targetPitch = Math.toDegrees(orientation[1].toDouble()).toFloat()
        val targetRoll = Math.toDegrees(orientation[2].toDouble()).toFloat()

        val clampedPitch = max(-20f, min(20f, targetPitch))
        val clampedRoll = max(-30f, min(30f, targetRoll))

        currentPitch += smoothing * (clampedPitch - currentPitch)
        currentRoll += smoothing * (clampedRoll - currentRoll)

        _offsetFlow.value = ParallaxOffset(roll = currentRoll, pitch = currentPitch)
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}
