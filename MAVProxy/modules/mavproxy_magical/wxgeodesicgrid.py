from __future__ import division
from __future__ import print_function

from ctypes import *
import math
import os.path
import wx
import time
from wx import glcanvas
from pymavlink import quaternion

from OpenGL.GL import *

from MAVProxy.modules.lib import geodesic_grid
from MAVProxy.modules.lib import opengl
from MAVProxy.modules.lib import wavefront as wv

def color_from_wx(color):
    r, g, b = color
    return r / 255.0, g / 255.0, b / 255.0

def quaternion_to_axis_angle(q):
    a, b, c, d = q.q
    n = math.sqrt(b**2 + c**2 + d**2)
    if not n:
        return 0, 0, 0
    angle = 2 * math.acos(a)
    if angle > math.pi:
        angle = angle - 2 * math.pi
    return angle * b / n, angle * c / n, angle * d / n

class Renderer:
    def __init__(self, background):
        glClearColor(*background)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_MULTISAMPLE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        self.sections_triangles = geodesic_grid.sections_triangles
        self.visible = [False for _ in range(len(self.sections_triangles))]

        self.program = opengl.Program()
        self.program.compile_and_link()

        self.program.use_light(opengl.Light(
            position=(-2.0, 0.0, -1.0),
            ambient=[.8] * 3,
            diffuse=[.5] * 3,
            specular=[.25] * 3,
            att_linear=0.000,
            att_quad=0.000,
        ))

        self.common_model_transform = opengl.Transform()
        self.common_model_transform.rotate((0, 1, 0), math.radians(7))

        vertices = [p for t in self.sections_triangles for p in t]
        self.sphere = opengl.Object(vertices, enable_alpha=True)
        self.sphere.local.scale(0.46)
        self.sphere.model = self.common_model_transform

        self.base_color = (0.5, 0.5, 0.5)

        self.vehicle = None

        self.camera = opengl.Camera()
        self.camera.base = (
            ( 0, 1, 0),
            ( 0, 0,-1),
            (-1, 0, 0),
        )
        self.camera.position = (-100.0, 0, 0)

        near = -self.camera.position[0] - 1.0
        far = near + 2.0
        self.projection = opengl.Orthographic(near=near, far=far)
        self.program.use_projection(self.projection)

        self.mag = None

    def set_viewport(self, viewport):
        glViewport(*viewport)

    def get_load_progress(self):
        return self.vehicle_loader.get_progress()

    def rotate(self, vector, angle):
        self.common_model_transform.rotate(vector, angle)

    def set_attitude(self, roll, pitch, yaw):
        self.common_model_transform.set_euler(roll, pitch, yaw)

    def set_mag(self, x, y, z):
        x, y, z = self.common_model_transform.apply((x, y, z))
        x, y, z = opengl.normalize((x, y, z))

        if not self.mag:
            p = os.path
            path = p.join(p.dirname(__file__), 'data', 'arrow.obj')
            obj = wv.ObjParser(filename=path).parse()
            self.mag = opengl.WavefrontObject(obj)
            self.mag.local.scale(.88)

        axis = opengl.cross((0, 0, 1), (x, y, z))
        angle = math.acos(opengl.dot((0, 0, 1), (x, y, z)))
        self.mag.model.set_rotation(axis, angle)

    def render(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        self.program.use_camera(self.camera)

        if self.vehicle:
            self.vehicle.draw(self.program)

        self.sphere.material.set_color(tuple(1.2 * c for c in self.base_color))
        self.sphere.material.specular_exponent = 4
        self.sphere.material.alpha = 1.0
        glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        self.sphere.draw(self.program)

        if self.mag:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            self.mag.draw(self.program)

        self.sphere.material.set_color(self.base_color)
        self.sphere.material.alpha = .6
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        faces = [i for i in range(80) if self.visible[i]]
        self.sphere.draw(self.program, faces=faces, camera=self.camera)

    def set_section_visible(self, section, visible=True):
        self.visible[section] = visible

    def clear_sections(self):
        for i in range(len(self.visible)):
            self.visible[i] = False

    def set_vehicle_wavefront(self, vehicle):
        self.vehicle = opengl.WavefrontObject(vehicle)
        self.vehicle.local.scale(3.5)
        self.vehicle.model = self.common_model_transform


class GeodesicGrid(glcanvas.GLCanvas):
    def __init__(self, *k, **kw):
        kw['attribList'] = (glcanvas.WX_GL_SAMPLES, 4, )
        super(GeodesicGrid, self).__init__(*k, **kw)
        self.context = glcanvas.GLContext(self)
        self.renderer = None
        self.vehicle_wavefront = None

        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
        self.Bind(wx.EVT_MOTION, self.OnMotion)

        self.attitude_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnAttitudeTimer, self.attitude_timer)
        self.attitude_timer.Start(5)

        self.gyro = 0.0, 0.0, 0.0
        self.mag = 0.0, 0.0, 0.0
        self.filtered_mag = 0.0, 0.0, 0.0
        self.attitude_timer_last = 0
        self.attitude_timestamp = 0

    def SetVehicleWavefront(self, vehicle):
        if self.renderer:
            self.renderer.set_vehicle_wavefront(vehicle)
            self.Refresh()
            return
        self.vehicle_wavefront = vehicle

    def SetMag(self, x, y, z):
        self.mag = x, y, z

    def SetAttitude(self, roll, pitch, yaw, timestamp):
        if not self.renderer:
            return

        dt = 0xFFFFFFFF & (timestamp - self.attitude_timestamp)
        dt *= 0.001
        self.attitude_timestamp = timestamp

        desired_quaternion = quaternion.Quaternion((roll, pitch, yaw))
        desired_quaternion.normalize()
        error = desired_quaternion / self.renderer.common_model_transform.quaternion
        error.normalize()
        x, y, z = quaternion_to_axis_angle(error)

        self.gyro = x / dt, y / dt, z / dt

    def OnAttitudeTimer(self, evt):
        if not self.renderer:
            return

        t = time.time()
        dt = t - self.attitude_timer_last
        self.attitude_timer_last = t

        x, y, z = self.gyro
        angle = math.sqrt(x**2 + y**2 + z**2)
        angle *= dt

        fmx, fmy, fmz = self.filtered_mag
        mx, my, mz = self.mag
        alpha = 0.8
        self.filtered_mag = (
            fmx * alpha + (1 - alpha) * mx,
            fmy * alpha + (1 - alpha) * my,
            fmz * alpha + (1 - alpha) * mz,
        )

        self.renderer.rotate((x, y, z), angle)
        self.renderer.set_mag(*self.filtered_mag)
        self.Refresh()

    def CalcRotationVector(self, dx, dy):
        angle = math.degrees(math.atan2(dy, dx))
        # Make angle discrete on multiples of 45 degrees
        angle = angle + 22.5 - (angle + 22.5) % 45

        if angle % 90 == 45:
            x, y = 1, 1
        elif (angle / 90) % 2 == 0:
            x, y = 1, 0
        else:
            x, y = 0, 1

        if abs(angle) > 90:
            x *= -1
        if angle < 0:
            y *= -1

        # NED coordinates from the camera point of view
        dx, dy, dz = 0, x, y
        # Get rotation axis by rotating the moving vector -90 degrees on x axis
        self.rotation_vector = (dx, dz, -dy)

    def GetDeltaAngle(self):
        radius = 60.0
        pos = wx.GetMousePosition()
        d = pos - self.motion_reference
        self.motion_reference = pos

        self.CalcRotationVector(d.x, d.y)

        arc = math.sqrt(d.x**2 + d.y**2)
        return arc / radius

    def OnPaint(self, evt):
        w, h = self.GetClientSize()
        e = min(w, h)
        if not e:
            return

        self.SetCurrent(self.context)

        if not self.renderer:
            r, g, b = color_from_wx(self.GetParent().GetBackgroundColour())
            self.renderer = Renderer(
                background=(r, g, b, 1),
            )
            if self.vehicle_wavefront:
                self.renderer.set_vehicle_wavefront(self.vehicle_wavefront)
                self.vehicle_wavefront = None

            if hasattr(self, 'base_color'):
                self.renderer.base_color = self.base_color
                del self.base_color

        x, y = int((w - e) / 2), int((h - e) / 2)
        self.renderer.set_viewport((x, y, e, e))
        self.renderer.render()

        self.SwapBuffers()

    def OnLeftDown(self, evt):
        self.motion_reference = wx.GetMousePosition()

    def OnMotion(self, evt):
        if not evt.Dragging() or not evt.LeftIsDown():
            return

        angle = self.GetDeltaAngle()
        self.renderer.rotate(self.rotation_vector, angle)

        self.Refresh()

    def UpdateVisibleSections(self, visible):
        for i, v in enumerate(visible):
            self.renderer.set_section_visible(i, v)
        self.Refresh()

    def SetColor(self, color):
        ''' color *must* be a wx.Colour object or at least a sequence
        containing the red, green and blue components (from 0 to 255). It seems
        like wxpython doesn't provide a standard function to construct a color
        from any of the allowed specifiers. '''
        if self.renderer:
            self.renderer.base_color = color_from_wx(color)
        else:
            self.base_color = color_from_wx(color)
        self.Refresh()
