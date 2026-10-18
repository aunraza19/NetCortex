# NetCortex CHR baseline: a small ISP edge router. Applied once on first start, then saved
# as var/chr/baseline.qcow2. Every template dry run must leave the config exactly like this.
#
# ether1 = primary uplink (QEMU user network: router 10.0.2.15, gateway 10.0.2.2; the
#          REST/SSH port forwards arrive here, so its address must not change)
# ether2 = backup uplink (192.0.2.2/30, gateway 192.0.2.1; TEST-NET, isolated)
# ether3 = LAN (10.0.0.1/24; subscribers 10.0.0.42 and 10.0.0.57)

/interface ethernet set [find default-name=ether1] comment="primary uplink"
/interface ethernet set [find default-name=ether2] comment="backup uplink"
/interface ethernet set [find default-name=ether3] comment="LAN"

# A static default route instead of the DHCP one, so failover_route can set check-gateway.
/ip dhcp-client set [find interface=ether1] add-default-route=no
/ip route add dst-address=0.0.0.0/0 gateway=10.0.2.2 distance=1 comment="primary default"

/ip address add address=192.0.2.2/30 interface=ether2 comment="backup uplink"
/ip address add address=10.0.0.1/24 interface=ether3 comment="LAN"

# One simple queue per subscriber, as small WISPs usually have.
/queue simple add name=sub-10.0.0.42 target=10.0.0.42/32 max-limit=50M/50M
/queue simple add name=sub-10.0.0.57 target=10.0.0.57/32 max-limit=50M/50M

# Upstream resolver the router uses (the ISP's, in this lab a TEST-NET address).
/ip dns set servers=192.0.2.53 allow-remote-requests=yes
