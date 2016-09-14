from OpenGL.GL import *
from pymavlink import quaternion
from ctypes import *
import math

def cross(a, b):
    ax, ay, az = a
    bx, by, bz = b
    return ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx

def dot(a, b):
    ax, ay, az = a
    bx, by, bz = b
    return ax * bx + ay * by + az * bz

def length(a):
    ax, ay, az = a
    return math.sqrt(ax**2 + ay**2 + az**2)

def normalize(a):
    ax, ay, az = a
    l = length(a)
    if not l:
        return 0, 0, 0
    return ax / l, ay / l, az / l

def midpoint(vectors):
    mx, my, mz = 0.0, 0.0, 0.0
    for x, y, z in vectors:
        mx, my, mz = mx + x, my + y, mz + z
    n = len(vectors)
    return mx / n, my / n, mz / n

class Material(object):
    def __init__(self,
                 ambient=(.5, .5, .5),
                 diffuse=(.5, .5, .5),
                 specular=(.5, .5, .5),
                 specular_exponent=32.0,
                 alpha=1.0):
        self.ambient = ambient
        self.diffuse = diffuse
        self.specular = specular
        self.specular_exponent = specular_exponent
        self.alpha = alpha

    def set_color(self, color):
        self.ambient = color
        self.diffuse = color
        self.specular = color

class Light(object):
    def __init__(self,
                 position=(0.0, 0.0, 1.0),
                 ambient=(1.0, 1.0, 1.0),
                 diffuse=(1.0, 1.0, 1.0),
                 specular=(1.0, 1.0, 1.0),
                 att_linear=0.0,
                 att_quad=0.0):
        self.position = position
        self.ambient = ambient
        self.diffuse = diffuse
        self.specular = specular
        self.att_linear = att_linear
        self.att_quad = att_quad

class Transform(object):
    '''Class to represent transform operations. Note that the operations
    provided are isolated from each other, in the sense that the sequence of
    operations is always: rotation, scale and translation. That means that an
    operation add to itself and the final outcome will always be in the
    following order: accumulated scale, accumulated rotation and accumulated
    translation.'''
    def __init__(self):
        self.quaternion = quaternion.Quaternion((1, 0, 0, 0))
        self.translation = 0.0, 0.0, 0.0
        self.scale_factor = 1.0

    def scale(self, scale):
        self.scale_factor *= scale

    def rotation_quaternion(self, vector, angle):
        x, y, z = vector
        n = math.sqrt(x**2 + y**2 + z**2)
        if not n:
            return None
        s = math.sin(angle / 2.0)
        c = math.cos(angle / 2.0)
        q = quaternion.Quaternion((c, s * x / n, s * y / n, s * z / n))
        q.normalize()
        return q


    def rotate(self, vector, angle):
        q = self.rotation_quaternion(vector, angle)
        if not q:
            return
        self.quaternion = q * self.quaternion
        self.quaternion.normalize()

    def set_rotation(self, vector, angle):
        q = self.rotation_quaternion(vector, angle)
        if not q:
            return
        self.quaternion = q

    def set_euler(self, roll, pitch, yaw):
        self.quaternion = quaternion.Quaternion((roll, pitch, yaw))
        self.quaternion.normalize()

    def translate(self, dx, dy, dz):
        x, y, z = self.translation
        self.translation = x + dx, y + dy, z + dz

    def mat4(self):
        s = self.scale_factor
        m = self.quaternion.dcm
        dx, dy, dz = self.translation
        return (c_float * 16)(
            s * m.a.x, s * m.b.x, s * m.c.x, 0,
            s * m.a.y, s * m.b.y, s * m.c.y, 0,
            s * m.a.z, s * m.b.z, s * m.c.z, 0,
                   dx,        dy,        dz, 1
        )

    def apply(self, v):
        x, y, z = v
        s = self.scale_factor
        m = self.quaternion.dcm
        dx, dy, dz = self.translation

        ax, ay, az = s * m.a.x, s * m.a.y, s * m.a.z
        bx, by, bz = s * m.b.x, s * m.b.y, s * m.b.z
        cx, cy, cz = s * m.c.x, s * m.c.y, s * m.c.z

        return (ax * x + ay * y + az * z + dx,
                bx * x + by * y + bz * z + dy,
                cx * x + cy * y + cz * z + dz)

class Camera(object):
    def __init__(self):
        # Base must be orthonormal
        self.base = (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0)
        )
        self.position = 0.0, 0.0, 0.0
        self.position_transform = Transform()
        self.base_transform = Transform()

    def view_mat4(self):
        p = self.position_transform.apply(self.position)
        i = ix, iy, iz = self.base_transform.apply(self.base[0])
        j = jx, jy, jz = self.base_transform.apply(self.base[1])
        k = kx, ky, kz = self.base_transform.apply(self.base[2])
        tx, ty, tz = dot(p, i), dot(p, j), dot(p, k)

        return (c_float * 16)(
             ix,  jx,  kx, 0,
             iy,  jy,  ky, 0,
             iz,  jz,  kz, 0,
            -tx, -ty, -tz, 1
        )

class Orthographic(object):
    def __init__(self, near=0.0, far=2.0, top=1.0, right=1.0):
        self.near = near
        self.far = far
        self.top = top
        self.right = right

    def proj_mat4(self):
        n = self.near
        f = self.far
        t = self.top
        r = self.right
        return (c_float * 16)(
            1 / r, 0, 0, 0,
            0, 1 / t, 0, 0,
            0, 0, -2 / (f - n), 0,
            0, 0, -(f + n) / (f - n), 1
        )


class Perspective(object):
    def __init__(self, near=0.01, far=100.0, top=0.24, right=0.24):
        self.near = near
        self.far = far
        self.top = top
        self.right = right

    def proj_mat4(self):
        n = self.near
        f = self.far
        t = self.top
        r = self.right
        return (c_float * 16)(
            n / r, 0, 0, 0,
            0, n / t, 0, 0,
            0, 0, -(f + n) / (f - n), -1,
            0, 0, -2 * f * n / (f - n), 0
        )

class Object(object):
    def __init__(self, vertices,
                 normals=[],
                 indices=[],
                 material=Material(),
                 vertices_per_face=3,
                 enable_alpha=False):
        self.local = Transform()
        self.model = Transform()
        self.num_vertices = len(vertices)
        self.midpoint = midpoint(vertices)

        self.material = material

        if not normals:
            normals = self.calc_normals(vertices)

        if not indices:
            indices = self.calc_indices(len(vertices), vertices_per_face)

        self.num_indices = len(indices)
        self.centroids = None
        if enable_alpha:
            self.centroids = self.calc_centroids(indices, vertices)

        self.vao = self.create_vao(vertices, normals, indices)

    def create_vao(self, vertices, normals, indices):
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)

        vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)

        vertices = [x for p in vertices for x in p]
        normals = [x for p in normals for x in p]

        data = vertices + normals
        data = (c_float * len(data))(*data)

        glBufferData(GL_ARRAY_BUFFER, data, GL_STATIC_DRAW);

        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, c_void_p(0))
        glEnableVertexAttribArray(0)

        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 0,
                              c_void_p(sizeof(c_float) * len(vertices)))
        glEnableVertexAttribArray(1)

        ebo = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo)
        data = (c_int * len(indices))(*indices)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, data, GL_STATIC_DRAW);

        glBindVertexArray(0)

        return vao

    def calc_centroids(self, indices, vertices):
        num_faces = len(indices) / 3
        centroids = []
        for i in range(num_faces):
            ax, ay, az = vertices[indices[i * 3]]
            bx, by, bz = vertices[indices[i * 3 + 1]]
            cx, cy, cz = vertices[indices[i * 3 + 2]]
            centroids.append((
                (ax + bx + cx) / 3.0,
                (ay + by + cy) / 3.0,
                (az + bz + cz) / 3.0,
            ))
        return centroids

    def before_draw(self, program, enable_alpha=False):
        glUseProgram(program.program_id)
        program.use_local_transform(self.local)
        program.use_model_transform(self.model)
        if self.material:
            program.use_material(self.material, enable_alpha=enable_alpha)
        glBindVertexArray(self.vao)

    def after_draw(self, program):
        glBindVertexArray(0)

    def draw(self, program, faces=None, camera=None):
        has_alpha = self.material and self.centroids and camera
        self.before_draw(program, has_alpha)

        if has_alpha:
            cx, cy, cz = camera.position
            if faces is None:
                num_faces = self.num_indices / 3
                faces = [i for i in range(num_faces)]
            # Sort faces based on ditance between centroids and camera position
            dists = {}
            for i in faces:
                x, y, z = self.model.apply(self.local.apply(self.centroids[i]))
                dists[i] = length((cx - x, cy - y, cz - z))
            faces = sorted(faces, None, lambda i: dists[i])

        if faces is None:
            glDrawElements(GL_TRIANGLES, self.num_indices, GL_UNSIGNED_INT, None)
        else:
            for i in faces:
                glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_INT, c_void_p(sizeof(c_uint) * i * 3))
        self.after_draw(program)

    def calc_indices(self, num_vertices, vertices_per_face):
        num_faces = int(num_vertices / vertices_per_face)
        indices = []
        for i in range(num_faces):
            i0 = i * vertices_per_face
            ia = i0 + 1
            for _ in range(vertices_per_face - 2):
                ib = ia + 1
                indices.append(i0)
                indices.append(ia)
                indices.append(ib)
                ia = ib
        return indices

    def calc_normals(self, vertices):
        def normal(polygon):
            ax, ay, az = polygon[0]
            bx, by, bz = polygon[1]
            cx, cy, cz = polygon[2]
            v1 = bx - ax, by - ay, bz - az
            v2 = cx - ax, cy - ay, cz - az
            n = cross(v1, v2)

            pmx, pmy, pmz = midpoint(polygon)
            mx, my, mz = self.midpoint
            direction = pmx - mx, pmy - my, pmz - mz
            if dot(n, direction) < 0:
                n = -n[0], -n[1], -n[2]

            return n

        normals = []
        for i in range(0, self.num_vertices, 3):
            n = normal(vertices[i:i+3])
            normals.extend([n, n, n])
        return normals

class Cube(Object):
    def __init__(self, material=Material()):
        vertices = (
            (-1.0, -1.0, -1.0),
            ( 1.0, -1.0, -1.0),
            ( 1.0,  1.0, -1.0),
            (-1.0,  1.0, -1.0),

            (-1.0, -1.0,  1.0),
            ( 1.0, -1.0,  1.0),
            ( 1.0,  1.0,  1.0),
            (-1.0,  1.0,  1.0),

            (-1.0, -1.0, -1.0),
            (-1.0,  1.0, -1.0),
            (-1.0,  1.0,  1.0),
            (-1.0, -1.0,  1.0),

            ( 1.0, -1.0, -1.0),
            ( 1.0,  1.0, -1.0),
            ( 1.0,  1.0,  1.0),
            ( 1.0, -1.0,  1.0),

            (-1.0, -1.0, -1.0),
            ( 1.0, -1.0, -1.0),
            ( 1.0, -1.0,  1.0),
            (-1.0, -1.0,  1.0),

            (-1.0,  1.0, -1.0),
            ( 1.0,  1.0, -1.0),
            ( 1.0,  1.0,  1.0),
            (-1.0,  1.0,  1.0),
        )
        super(Cube, self).__init__(
            vertices=vertices,
            material=material,
            vertices_per_face=4,
        )


class WavefrontObject(Object):
    def __init__(self, obj):
        vertices, normals, indices, material_sequence = WavefrontObject.calc_arrays(obj)
        super(WavefrontObject, self).__init__(
            vertices=vertices,
            normals=normals,
            indices=indices,
            material=None,
        )
        self.material_sequence = material_sequence

    def draw(self, program):
        self.before_draw(program)

        if self.material_sequence:
            for j in range(len(self.material_sequence) - 1):
                i, m = self.material_sequence[j]
                next_i, _ = self.material_sequence[j + 1]
                program.use_material(m)
                glDrawElements(GL_TRIANGLES, next_i - i, GL_UNSIGNED_INT, c_void_p(sizeof(c_uint) * i));
            i, m = self.material_sequence[-1]
            program.use_material(m)
            glDrawElements(GL_TRIANGLES, self.num_indices - i, GL_UNSIGNED_INT, c_void_p(sizeof(c_uint) * i));

        self.after_draw(program)

    @staticmethod
    def calc_arrays(obj):
        vertices = []
        normals = []
        indices = []
        # stores tuples with the material and the starting index for the
        # elements vertices
        material_sequence = []

        # mapped with vertex index and normal index
        indices_dict = {}

        current_mtl = None
        material_map = {}
        def mtl_to_material(mtl):
            if mtl.name not in material_map:
                m = Material(
                    ambient=mtl.Ka,
                    diffuse=mtl.Kd,
                    specular=mtl.Ks,
                    specular_exponent=mtl.Ns,
                )
                material_map[mtl.name] = m
            return material_map[mtl.name]

        def index(i, j):
            if (i, j) not in indices_dict:
                indices_dict[(i, j)] = len(vertices)
                vertices.append(obj.vertices[i - 1][:3])
                normals.append(obj.normals[j - 1])
            return indices_dict[(i, j)]

        for f in obj.faces:
            vertex_data, mtl = f

            if not current_mtl or mtl.name != current_mtl.name:
                current_mtl = mtl
                material_sequence.append((len(indices), mtl_to_material(mtl)))

            i0 = index(vertex_data[0][0], vertex_data[0][2])
            ia = index(vertex_data[1][0], vertex_data[1][2])
            for i in range(2, len(vertex_data)):
                ib = index(vertex_data[i][0], vertex_data[i][2])
                indices.append(i0)
                indices.append(ia)
                indices.append(ib)
                ia = ib

        return vertices, normals, indices, material_sequence

class Program:
    shader_type_names = {
        GL_COMPUTE_SHADER: 'compute shader',
        GL_VERTEX_SHADER: 'vertex shader',
        GL_TESS_CONTROL_SHADER: 'tessellation control shader',
        GL_TESS_EVALUATION_SHADER: 'tessellation evaluation shader',
        GL_GEOMETRY_SHADER: 'geometry shader',
        GL_FRAGMENT_SHADER: 'fragment shader',
    }

    default_shaders = {
        GL_VERTEX_SHADER: '''
            #version 330 core

            layout (location = 0) in vec3 v;
            layout (location = 1) in vec3 normal;

            out vec3 v_normal;
            out vec3 v_v;

            uniform mat4 local = mat4(
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            );

            uniform mat4 model = mat4(
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            );

            uniform mat4 view = mat4(
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            );

            uniform mat4 proj = mat4(
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            );


            void main()
            {
                mat4 transform = model * local;
                v_v = vec3(transform * vec4(v, 1.0));
                v_normal = vec3(transform * vec4(normal, 1.0));

                gl_Position = proj * view * vec4(v_v, 1.0);
            }
        ''',
        GL_FRAGMENT_SHADER: '''
            #version 330 core

            in vec3 v_normal;
            in vec3 v_v;

            out vec4 color;

            struct Light {
                vec3 pos;
                vec3 ambient;
                vec3 diffuse;
                vec3 specular;
                float att_linear;
                float att_quad;
            };

            struct Material {
                vec3 ambient;
                vec3 diffuse;
                vec3 specular;
                float specular_exponent;
                float alpha;
            };

            uniform Light light = Light(
                vec3(1.0, 1.0, 1.0),
                vec3(1.0, 1.0, 1.0),
                vec3(1.0, 1.0, 1.0),
                vec3(1.0, 1.0, 1.0),
                0.0,
                0.0
            );

            uniform Material material = Material(
                vec3(.5, .5, .5),
                vec3(.5, .5, .5),
                vec3(.5, .5, .5),
                32.0,
                1.0
            );

            uniform vec3 camera_position = vec3(-1.0, 0.0, 0.0);

            void main()
            {
                vec3 view_direction = normalize(camera_position - v_v);
                vec3 light_direction = normalize(light.pos - v_v);

                vec3 normal = normalize(v_normal);
                /* If triangle is opposed to the camera, then color the other
                 * side. */
                if (dot(normal, view_direction) < 0)
                    normal = -normal;


                float cos_theta = dot(normal, light_direction);
                if (cos_theta < 0) {
                    cos_theta = 0;
                }
                vec3 diffuse = cos_theta * light.diffuse * material.diffuse;

                vec3 reflection = reflect(-light_direction, normal);
                cos_theta = dot(reflection, view_direction);
                if (cos_theta < 0) {
                    cos_theta = 0;
                }
                vec3 specular = pow(cos_theta, material.specular_exponent) *
                                light.specular * material.specular;

                vec3 ambient = light.ambient * material.ambient;

                float dist = length(light.pos - v_v);
                float attenuation = 1.0 / (1.0 + light.att_linear * dist + light.att_quad * dist * dist);

                color = vec4(attenuation * (diffuse + specular + ambient), material.alpha);
            }
        ''',
    }

    def __init__(self):
        self.shaders = dict(self.default_shaders)
        self.uniforms = {k: None for k in (
            'local',
            'model',
            'view',
            'proj',
            'camera_position',
            'light.pos',
            'light.ambient',
            'light.diffuse',
            'light.specular',
            'light.att_linear',
            'light.att_quad',
            'material.ambient',
            'material.diffuse',
            'material.specular',
            'material.specular_exponent',
            'material.alpha',
        )}

    def shader_code(shader_type, code):
        self.shaders[shader_type] = code

    def compile_and_link(self):
        self.program_id = glCreateProgram()
        if not self.program_id:
            raise Exception('Error on creating the OpenGL program')

        shader_ids = []
        try:
            for shader_type, code in self.shaders.items():
                shader_id = glCreateShader(shader_type)
                name = self.shader_type_names[shader_type]
                if not shader_id:
                    raise Exception("Error on creating %s" % name)
                shader_ids.append(shader_id)
                glShaderSource(shader_id, code)
                glCompileShader(shader_id)
                if glGetShaderiv(shader_id, GL_COMPILE_STATUS) != GL_TRUE:
                    error_string = glGetShaderInfoLog(shader_id)
                    raise Exception("Error on compiling %s: %s" % (name, error_string))
                glAttachShader(self.program_id, shader_id)
            glLinkProgram(self.program_id)
            if glGetProgramiv(self.program_id, GL_LINK_STATUS) != GL_TRUE:
                raise Exception('Error on linking the OpenGL program')
        finally:
            for i in shader_ids:
                glDeleteShader(i)

        for k in self.uniforms:
            self.uniforms[k] = glGetUniformLocation(self.program_id, k)
            if self.uniforms[k] < 0:
                raise Exception("Couldn't get location for uniform %s" % k)

    def use_material(self, material, enable_alpha=False):
        glUseProgram(self.program_id)
        glUniform3f(self.uniforms['material.ambient'], *material.ambient)
        glUniform3f(self.uniforms['material.diffuse'], *material.diffuse)
        glUniform3f(self.uniforms['material.specular'], *material.specular)
        glUniform1f(self.uniforms['material.specular_exponent'], material.specular_exponent)
        alpha = material.alpha if enable_alpha else 1.0
        glUniform1f(self.uniforms['material.alpha'], alpha)

    def use_light(self, light):
        glUseProgram(self.program_id)
        glUniform3f(self.uniforms['light.pos'], *light.position)
        glUniform3f(self.uniforms['light.ambient'], *light.ambient)
        glUniform3f(self.uniforms['light.diffuse'], *light.diffuse)
        glUniform3f(self.uniforms['light.specular'], *light.specular)
        glUniform1f(self.uniforms['light.att_linear'], light.att_linear)
        glUniform1f(self.uniforms['light.att_quad'], light.att_quad)

    def use_local_transform(self, transform):
        glUseProgram(self.program_id)
        m = transform.mat4()
        glUniformMatrix4fv(self.uniforms['local'], 1, GL_FALSE, m)

    def use_model_transform(self, transform):
        glUseProgram(self.program_id)
        m = transform.mat4()
        glUniformMatrix4fv(self.uniforms['model'], 1, GL_FALSE, m)

    def use_camera(self, camera):
        glUseProgram(self.program_id)
        m = camera.view_mat4()
        glUniform3f(self.uniforms['camera_position'], *camera.position)
        glUniformMatrix4fv(self.uniforms['view'], 1, GL_FALSE, m)

    def use_projection(self, projection):
        glUseProgram(self.program_id)
        m = projection.proj_mat4()
        glUniformMatrix4fv(self.uniforms['proj'], 1, GL_FALSE, m)

